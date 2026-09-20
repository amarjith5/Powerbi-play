"""
Chat Engine — Intent detection + confidence-gated report routing +
structured response generation + critic loop + numeric fact-check
"""
import asyncio
import json
import re
from llm_client import LLMClient
from powerbi_client import PowerBIClient
from models import ChatRequest, ChatResponse, ChartData, IntentType

try:
    from json_repair import repair_json
    _HAS_JSON_REPAIR = True
except ImportError:
    _HAS_JSON_REPAIR = False

llm = LLMClient()
pbi = PowerBIClient()

# Below this, we don't silently auto-load a report — we suggest it instead.
CONFIDENCE_THRESHOLD = 0.7

# Response length caps by intent. Data-lookup style questions rarely need
# more than a short paragraph + chart; explanation/summary questions get
# more room to breathe. Keeping these well below the old flat 4000 is the
# single biggest lever on response latency, since generation time scales
# with token count.
MAX_TOKENS_BY_INTENT = {
    IntentType.DATA_QUERY: 800,
    IntentType.COMPARISON: 1000,
    IntentType.TREND: 1000,
    IntentType.EXPLANATION: 2000,
    IntentType.GENERAL: 1000,
}
DEFAULT_MAX_TOKENS = 1000

INTENT_SYSTEM_TEMPLATE = """You are an intent classifier and router for a Power BI analytics chatbot.

AVAILABLE REPORTS:
{report_catalog}

Classify the user's message into exactly one of these intents:
- data_query: asking for specific numbers or metrics
- comparison: comparing two or more things (regions, products, time periods)
- trend: asking about changes over time
- explanation: asking what something means, how the tool works, or general orientation
- general: greeting, small talk, or a question unrelated to any specific data

If the message needs real report data to answer (data_query, comparison, trend) AND
no report is already loaded, pick the single best-matching report id from the list above,
and give a confidence score from 0.0 (pure guess) to 1.0 (certain match).
If no report matches well, or none is needed (explanation/general), set report_id to null
and confidence to 0.0.

Respond with ONLY a JSON object, strictly valid JSON with no markdown fences, no trailing
commas, and all newlines/quotes/backslashes inside string values properly escaped, like:
{{"intent": "data_query", "report_id": "rpt-001", "confidence": 0.9}}
or
{{"intent": "general", "report_id": null, "confidence": 0.0}}"""

ANALYST_SYSTEM = """You are BISync, an intelligent Power BI analytics assistant.
You have access to real report data provided in the context. Be specific, cite actual numbers.

Rules:
1. Always ground your answer in the provided data — never invent figures
2. When data supports it, suggest a chart type (bar/line/pie) with labels and values
3. Provide 3 short follow-up question suggestions
4. Keep answers concise but insightful — highlight what matters most
5. Format numbers clearly: use $, %, K/M suffixes

Respond ONLY with a single valid JSON object — no markdown code fences, no trailing commas,
no comments, and no control characters inside string values (write newlines inside strings
as the two characters \\n, not a literal line break; escape any backslash as \\\\ and any
double quote as \\"). Double-check the JSON is syntactically complete before responding.

{
  "answer": "your detailed answer here",
  "chart": {
    "type": "bar|line|pie",
    "labels": ["label1", "label2"],
    "values": [100, 200],
    "title": "Chart title"
  },
  "follow_up_questions": ["Q1?", "Q2?", "Q3?"],
  "data_used": "brief note on which data you used"
}
If no chart is appropriate, set "chart": null."""

EXPLAINER_SYSTEM_TEMPLATE = """You are BISync, a friendly guide helping a new user get oriented with a
Power BI analytics chatbot. No specific report data is loaded right now.

AVAILABLE REPORTS:
{report_catalog}
{suggestion_note}
Answer the user's question helpfully — explain what BISync does, what reports are available,
or answer general business questions from your own knowledge. Do NOT invent specific figures
or metrics, since no report data is loaded. If their question would need real data, gently
suggest which report they should open (or say you'll pull it up for them).

Respond ONLY with a single valid JSON object — no markdown code fences, no trailing commas,
no comments, and no control characters inside string values (write newlines inside strings
as the two characters \\n, not a literal line break; escape any backslash as \\\\ and any
double quote as \\"). Double-check the JSON is syntactically complete before responding.

{{
  "answer": "your helpful answer here",
  "chart": null,
  "follow_up_questions": ["Q1?", "Q2?", "Q3?"],
  "data_used": null
}}"""

CRITIC_SYSTEM = """You are a quality critic for BI analytics responses.
Check if the response is:
1. Grounded in actual data (no invented numbers)
2. Logically consistent
3. Answers the original question

Respond ONLY with a single valid JSON object — no markdown code fences, no trailing commas,
no comments, and no unescaped control characters inside string values.

If valid, respond: {"valid": true}
If not, respond: {"valid": false, "issue": "specific problem"}"""


def _parse_json_response(raw: str) -> dict:
    """
    Robustly parse a JSON object out of an LLM's raw text response.
    Strips markdown fences, tolerates raw control characters inside strings,
    and falls back to json_repair for structurally broken JSON (missing
    commas/braces/quotes) if the library is installed.
    """
    clean = re.sub(r"```json|```", "", raw).strip()
    try:
        return json.loads(clean, strict=False)
    except json.JSONDecodeError:
        if _HAS_JSON_REPAIR:
            return json.loads(repair_json(clean), strict=False)
        raise


def build_report_catalog(reports: list) -> str:
    if not reports:
        return "No reports available."
    lines = [f"- {r.id}: {r.name} — {r.description}" for r in reports]
    return "\n".join(lines)


async def detect_intent(message: str, reports: list) -> tuple[IntentType, str | None, float]:
    catalog = build_report_catalog(reports)
    system = INTENT_SYSTEM_TEMPLATE.format(report_catalog=catalog)
    try:
        raw = await llm.chat(system, [{"role": "user", "content": message}], max_tokens=300)
        parsed = _parse_json_response(raw)
        intent = IntentType(parsed.get("intent", "general"))
        report_id = parsed.get("report_id")
        confidence = float(parsed.get("confidence", 0.0) or 0.0)
        return intent, report_id, confidence
    except Exception as e:
        print(f"\n⚠️ detect_intent parse failure: {e}\nRAW:\n{raw if 'raw' in dir() else '(no response)'}\n")
        return IntentType.GENERAL, None, 0.0


def build_data_context(report_context: str | None, data: dict | None) -> str:
    if not data:
        return "No specific report selected. Answer from general business knowledge."
    return f"""
LOADED REPORT: {report_context}
LIVE DATA:
{json.dumps(data, indent=2)}

Use this data to answer the user's question with specific figures.
"""


async def critic_check(question: str, answer: str, data_context: str) -> bool:
    check_prompt = f"""
Original question: {question}
Data available: {data_context[:500]}
Response given: {answer[:800]}
"""
    try:
        raw = await llm.chat(CRITIC_SYSTEM, [{"role": "user", "content": check_prompt}], max_tokens=300)
        parsed = _parse_json_response(raw)
        return parsed.get("valid", True)
    except Exception:
        return True


async def _background_critic_log(question: str, answer: str, data_context: str) -> None:
    """
    Fire-and-forget quality check. The user already has their answer by the
    time this runs — this exists purely so a flagged response shows up in
    your server logs for review, without adding latency to the request.
    """
    try:
        valid = await critic_check(question, answer, data_context)
        if not valid:
            print(f"\n⚠️ BACKGROUND CRITIC FLAGGED A RESPONSE\nQ: {question}\nA: {answer[:300]}\n")
    except Exception:
        pass


# ---------- Non-AI numeric fact-check (no extra LLM call, near-zero cost) ----------

_NUMBER_PATTERN = re.compile(r"\$?\d[\d,]*\.?\d*\s*[KMB%]?", re.IGNORECASE)


def _parse_number_token(token: str):
    token = token.strip()
    if not token or not any(ch.isdigit() for ch in token):
        return None
    is_percent = token.endswith("%")
    cleaned = token.replace("$", "").replace(",", "").rstrip("%").strip()
    multiplier = 1
    if cleaned and cleaned[-1].upper() in "KMB":
        multiplier = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[cleaned[-1].upper()]
        cleaned = cleaned[:-1]
    try:
        value = float(cleaned) * multiplier
    except ValueError:
        return None
    return ("percent", value) if is_percent else ("number", value)


def _extract_numbers(text: str):
    results = []
    for match in _NUMBER_PATTERN.findall(text):
        parsed = _parse_number_token(match)
        if parsed:
            results.append(parsed)
    return results


def _flatten_numeric_values(data):
    values = []
    if isinstance(data, dict):
        for v in data.values():
            values.extend(_flatten_numeric_values(v))
    elif isinstance(data, list):
        for v in data:
            values.extend(_flatten_numeric_values(v))
    elif isinstance(data, (int, float)):
        values.append(float(data))
    return values


def _roughly_matches(a: float, b: float, tolerance: float = 0.05) -> bool:
    if b == 0:
        return abs(a) < 1e-6
    return abs(a - b) / abs(b) <= tolerance


def fact_check_numbers(answer_text: str, dataset_metrics: dict | None) -> bool:
    """
    Best-effort, non-AI check: every number mentioned in the answer should be
    traceable back to something in the actual dataset (accounting for %,
    K/M/B suffixes, and rounding). Cheap and can't hallucinate — it's just
    arithmetic — but it's a heuristic, not a guarantee, so treat a 'fail'
    as a caution flag rather than absolute proof of error.
    """
    if not dataset_metrics:
        return True # nothing to verify against (explainer mode)

    claimed = _extract_numbers(answer_text)
    if not claimed:
        return True # answer made no numeric claims

    known_values = _flatten_numeric_values(dataset_metrics)
    if not known_values:
        return True

    for kind, value in claimed:
        candidates = {value}
        if kind == "percent":
            candidates.add(value / 100)
        candidates.update({value * 1000, value * 1_000_000, value / 1000, value / 1_000_000})
        if not any(_roughly_matches(c, m) for c in candidates for m in known_values):
            return False
    return True


# ------------------------------------------------------------------------------------

# Field names from the expected response schema. If the "answer" text is
# suspiciously short and matches one of these (or a truncated fragment of
# one), it's almost certainly a JSON-repair artifact — e.g. json_repair
# grabbing a piece of the "follow_up_questions" key and stuffing it into
# "answer" when the LLM's raw output got cut off mid-JSON. A real answer to
# a business question is never just a bare schema field name.
_SCHEMA_FIELD_NAMES = {
    "answer", "chart", "type", "labels", "values", "title",
    "follow_up_questions", "up_questions", "questions",
    "data_used", "used", "valid", "issue",
}


def _looks_like_corrupted_answer(answer: str) -> bool:
    """
    Cheap, non-AI sanity check: catches the case where JSON parsing/repair
    silently 'succeeds' but produces a nonsense answer (e.g. a leaked field
    name) instead of throwing a parse error. This runs in addition to, not
    instead of, the numeric fact-check and critic — those check accuracy,
    this checks that the answer is even coherent text in the first place.
    """
    if not answer:
        return True
    normalized = re.sub(r"[^a-z]", "", answer.lower())
    if not normalized:
        return True
    if normalized in _SCHEMA_FIELD_NAMES:
        return True
    # Very short answers with no spaces and no digits are unlikely to be a
    # genuine sentence-style answer to a business question.
    if len(answer.strip()) <= 20 and " " not in answer.strip() and not any(ch.isdigit() for ch in answer):
        return True
    return False


async def generate_response(request: ChatRequest, dataset_metrics: dict | None = None) -> ChatResponse:
    reports = pbi.get_reports()

    loaded_report_id = request.report_context
    auto_loaded = None
    suggested_report = None

    if loaded_report_id or dataset_metrics:
        # A report is already active (or its data was already fetched by the
        # caller) — we don't need to ask the LLM what this question is about
        # or which report it might belong to. Skips one full LLM round-trip
        # per message, which is the common case once a user has a report open.
        intent = IntentType.DATA_QUERY
        suggested_report_id, confidence = None, 0.0
    else:
        intent, suggested_report_id, confidence = await detect_intent(request.message, reports)

    if not dataset_metrics and not loaded_report_id and suggested_report_id:
        if confidence >= CONFIDENCE_THRESHOLD:
            try:
                dataset = pbi.get_dataset(suggested_report_id)
                dataset_metrics = dataset.metrics
                loaded_report_id = suggested_report_id
                auto_loaded = suggested_report_id
            except Exception:
                pass
        else:
            # Confidence too low to silently load — offer it instead.
            suggested_report = suggested_report_id

    data_context = build_data_context(loaded_report_id, dataset_metrics)

    if dataset_metrics:
        system_prompt = ANALYST_SYSTEM
    else:
        catalog = build_report_catalog(reports)
        note = ""
        if suggested_report:
            match = next((r for r in reports if r.id == suggested_report), None)
            if match:
                note = f"\nNOTE: The user's question might relate to '{match.name}' ({match.id}), but you're not certain — mention this as a suggestion rather than answering with invented figures.\n"
        system_prompt = EXPLAINER_SYSTEM_TEMPLATE.format(report_catalog=catalog, suggestion_note=note)

    messages = [
        *[{"role": m.role, "content": m.content} for m in request.history[-6:]],
        {"role": "user", "content": f"{request.message}\n\nCONTEXT:\n{data_context}"},
    ]

    max_tokens = MAX_TOKENS_BY_INTENT.get(intent, DEFAULT_MAX_TOKENS)

    for attempt in range(3):
        raw = None
        try:
            raw = await llm.chat(system_prompt, messages, max_tokens=max_tokens)
            parsed = _parse_json_response(raw)

            answer = parsed.get("answer", "I couldn't generate a response.")

            if _looks_like_corrupted_answer(answer):
                # The JSON "parsed" without raising, but the answer text
                # itself is nonsense (e.g. a leaked field name like
                # "up_questions") — almost always truncated/malformed raw
                # output that json_repair patched together wrong. Log it
                # loudly (this is a *silent* failure mode, unlike the
                # except block below) and force a retry rather than ever
                # showing this to the user.
                print(f"\n⚠️ CORRUPTED ANSWER DETECTED (attempt {attempt}): {answer!r}\nRAW:\n{raw}\n")
                if attempt < 2:
                    messages.append({"role": "assistant", "content": raw})
                    messages.append({"role": "user", "content": "Your previous response was malformed or incomplete. Please respond again with a complete, valid JSON object as instructed."})
                    continue
                else:
                    return ChatResponse(
                        answer="I ran into an issue putting together a clear answer. Could you try rephrasing your question?",
                        intent=intent,
                        follow_up_questions=["Can you rephrase the question?", "Which report are you looking at?"],
                        loaded_report=auto_loaded,
                        suggested_report=suggested_report,
                    )

            fact_ok = fact_check_numbers(answer, dataset_metrics)

            if fact_ok:
                # Free check passed — trust it and respond immediately.
                # Still run the LLM critic, but in the background, purely
                # for logging; it doesn't block or affect this response.
                asyncio.create_task(_background_critic_log(request.message, answer, data_context))
                is_valid = True
            else:
                # Numbers look off — worth the extra LLM call here to decide
                # whether to actually retry, same grace period as before.
                critic_valid = await critic_check(request.message, answer, data_context)
                is_valid = critic_valid or attempt >= 1

            if is_valid or attempt == 2:
                chart_data = None
                if parsed.get("chart"):
                    c = parsed["chart"]
                    chart_data = ChartData(
                        type=c.get("type", "bar"),
                        labels=c.get("labels", []),
                        values=c.get("values", []),
                        title=c.get("title", ""),
                    )
                data_used = parsed.get("data_used")
                if not fact_ok:
                    caution = "Note: some figures could not be automatically verified against the loaded data."
                    data_used = f"{data_used} {caution}" if data_used else caution

                return ChatResponse(
                    answer=answer,
                    intent=intent,
                    chart=chart_data,
                    follow_up_questions=parsed.get("follow_up_questions", []),
                    data_used=data_used,
                    loaded_report=auto_loaded,
                    suggested_report=suggested_report,
                )

            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": "Your response had inconsistencies. Please revise with accurate data."})

        except Exception as e:
            print(f"\n❌ CHAT ENGINE ERROR [Attempt {attempt}]: {str(e)}\n")
            if raw:
                print(f"RAW RESPONSE THAT FAILED TO PARSE:\n{raw}\n---\n")

            if attempt == 2:
                return ChatResponse(
                    answer="I encountered an issue processing your request. Please try rephrasing.",
                    intent=intent,
                    follow_up_questions=["Can you rephrase the question?", "Which report are you looking at?"],
                    loaded_report=auto_loaded,
                    suggested_report=suggested_report,
                )

    return ChatResponse(answer="Unable to generate response after retries.", intent=intent)
