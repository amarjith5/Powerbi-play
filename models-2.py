from pydantic import BaseModel
from typing import Optional, List, Any
from enum import Enum


class IntentType(str, Enum):
    DATA_QUERY = "data_query"
    COMPARISON = "comparison"
    TREND = "trend"
    EXPLANATION = "explanation"
    GENERAL = "general"


class ChatMessage(BaseModel):
    role: str # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = []
    report_context: Optional[str] = None


class ChartSeries(BaseModel):
    name: str
    values: List[float]


class ChartData(BaseModel):
    type: str # "bar", "line", "pie"
    labels: List[str]
    values: List[float] = []
    title: str
    # Multi-series charts (e.g. Open vs Closed per month) carry `series`
    # instead of a flat `values` array — one entry per named series, each
    # with its own values aligned to `labels`. None/omitted for the
    # original single-series shape, so existing chart responses are
    # unaffected. `stacked` only matters when `series` is set.
    series: Optional[List[ChartSeries]] = None
    stacked: bool = False


class ChatResponse(BaseModel):
    answer: str
    intent: IntentType
    chart: Optional[ChartData] = None
    # Live, filtered rows from query_tickets()/query_orders() — e.g. a
    # specific ticket lookup, a date-range filter, or a combined-filter
    # match. Distinct from `chart`, which is aggregate/summary data.
    # None when no live record-level query was needed for this question.
    records: Optional[List[dict]] = None
    follow_up_questions: List[str] = []
    data_used: Optional[str] = None
    # Set when the bot auto-detected AND confidently auto-loaded a report
    # the user hadn't manually selected.
    loaded_report: Optional[str] = None
    # Set when the bot suspects a report is relevant but confidence was too
    # low to auto-load silently — frontend can offer this as a click-to-confirm.
    suggested_report: Optional[str] = None


class ReportMeta(BaseModel):
    id: str
    name: str
    workspace: str
    description: str


class DatasetSummary(BaseModel):
    report_id: str
    metrics: dict
    last_refreshed: str