from typing import Any, Optional

from pydantic import BaseModel, Field

from app.schemas.chat import SourceChunk
from app.schemas.document import DocumentItem, DocumentUploadData


class ChatData(BaseModel):
    session_id: str
    answer: str
    sources: list[SourceChunk] = Field(default_factory=list)
    tool_called: Optional[str] = None
    tool_result: Optional[Any] = None
    tools: list[str] = Field(default_factory=list)
    tool_results: Optional[Any] = None
    tool_plan: Optional[Any] = None
    rewritten_question: Optional[str] = None
    operation_request: Optional[Any] = None


class SummaryData(BaseModel):
    document_id: str
    summary: dict[str, str]


class KeywordsData(BaseModel):
    document_id: str
    keywords: list[str]


class MetricItem(BaseModel):
    metric: str
    value: str
    context: str


class MetricsData(BaseModel):
    document_id: str
    metrics: list[MetricItem]


class ChatMessageItem(BaseModel):
    role: str
    content: str
    document_id: Optional[str] = None
    tool_name: Optional[str] = None
    created_at: str


class SessionHistoryData(BaseModel):
    session_id: str
    messages: list[ChatMessageItem]


class SessionDocumentItem(BaseModel):
    document_id: str
    filename: Optional[str] = None


class SessionItem(BaseModel):
    session_id: str
    documents: list[SessionDocumentItem] = Field(default_factory=list)
    message_count: int
    tool_names: list[str] = Field(default_factory=list)
    question: str = ""
    library: str = "enterprise"
    updated_at: str


class SessionListData(BaseModel):
    sessions: list[SessionItem]
