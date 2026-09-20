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


class ChartData(BaseModel):
    type: str # "bar", "line", "pie"
    labels: List[str]
    values: List[float]
    title: str


class ChatResponse(BaseModel):
    answer: str
    intent: IntentType
    chart: Optional[ChartData] = None
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