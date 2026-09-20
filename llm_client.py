import os
import json
import uuid
import asyncio
import websockets # pip install websockets>=15.0


class LLMClient:
    """
    Async WebSocket client for a Generative Engine gateway.
    All connection/model details come from environment variables only —
    nothing organization-specific is hardcoded in this file.
    Opens a FRESH connection per chat() call (not a shared/reused socket),
    which keeps concurrent requests from different users safely isolated.
    """

    def __init__(self):
        self.api_key = os.getenv("GENAI_API_KEY")
        self.uri = os.getenv("GENAI_WS_URL")
        self.workspace_id = os.getenv("GENAI_WORKSPACE_ID")

        self.model = os.getenv("GENAI_MODEL_NAME")
        self.provider = os.getenv("GENAI_PROVIDER", "bedrock")
        self.adapter_version = os.getenv("GENAI_ADAPTER_VERSION", "v2")

        self.default_max_tokens = int(os.getenv("GENAI_MAX_TOKENS", "2048"))
        self.temperature = float(os.getenv("GENAI_TEMPERATURE", "0.3"))

        self.total_timeout = 90 # hard cap per request, in seconds

    def _build_text(self, messages: list) -> str:
        """
        This API takes one 'text' field per request, not a messages array,
        so history + current message are flattened into one readable block.
        """
        parts = []
        for m in messages:
            role = m.get("role", "user").upper()
            content = m.get("content", "")
            parts.append(f"{role}: {content}")
        return "\n\n".join(parts)

    async def chat(self, system_prompt: str, messages: list, max_tokens: int | None = None) -> str:
        session_id = str(uuid.uuid4()) # unique per call, never shared across requests
        text = self._build_text(messages)
        tokens = max_tokens or self.default_max_tokens

        payload = {
            "action": "run",
            "modelInterface": "multimodal",
            "adapterInterfaceVersion": self.adapter_version,
            "data": {
                "mode": "chain",
                "text": text,
                "modelName": self.model,
                "provider": self.provider,
                "sessionId": session_id,
                "workspaceId": self.workspace_id,
                "systemPrompt": system_prompt,
                "modelKwargs": {
                    "maxTokens": tokens,
                    "temperature": self.temperature,
                    "streaming": True,
                    "topP": 0.9,
                },
                "ragKwargs": {
                    "docLimit": 10
                },
            },
        }

        async def _run():
            headers = [("x-api-key", self.api_key)]
            async with websockets.connect(self.uri, additional_headers=headers) as ws:
                await ws.send(json.dumps(payload))

                answer_parts = []
                while True:
                    raw = await ws.recv()
                    parsed = json.loads(raw)
                    print(f"\nFULL PAYLOAD: {json.dumps(parsed, indent=2)}\n")
                    action = parsed.get("action")

                    print(f"\nSTATUS: streaming\nACTION: {action}\n")

                    if action == "llm_new_token":
                        token = parsed.get("data", {}).get("token", {}).get("value", "")
                        answer_parts.append(token)

                    elif action == "final_response":
                        final_data = parsed.get("data")
                        if isinstance(final_data, str) and final_data.strip():
                            return final_data
                        return "".join(answer_parts)

                    elif action == "error":
                        raise Exception(f"Generative Engine error: {parsed.get('data')}")

        try:
            return await asyncio.wait_for(_run(), timeout=self.total_timeout)
        except asyncio.TimeoutError:
            raise Exception(f"Generative Engine timed out after {self.total_timeout}s")
        except Exception as e:
            raise Exception(f"WebSocket error: {str(e)}")