from typing import Any, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, description="用户问题")
    session_id: Optional[str] = Field(default=None, description="当前对话 ID；不传则自动创建，前端自动保存")
    document_id: Optional[str] = Field(default=None, description="限定检索或工具调用的文档 ID")
    top_k: int = Field(default=4, ge=1, le=10, description="检索相关 chunk 数量")
    model: Optional[str] = Field(default=None, description="覆盖默认模型")
    provider: Optional[str] = Field(default=None, description="模型 provider：ollama / deepseek / openai / qwen")
    library: str = Field(default="enterprise", description="文档库：enterprise / research")
    permission_mode: str = Field(default="read_only", description="权限模式：read_only（仅知识库检索）/ approve_execute（可执行命令和写文件）")


class SourceChunk(BaseModel):
    filename: str
    chunk_id: str
    similarity_score: Optional[float] = None
    content_preview: str
    document_id: Optional[str] = None
    page: Optional[int] = None


class ChatResponseData(BaseModel):
    session_id: str
    answer: str
    sources: list[SourceChunk] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    tool_results: Optional[Any] = None
    operation_request: Optional[Any] = None


class StatsData(BaseModel):
    total_questions: int
    average_response_time_ms: float
    knowledge_base_hit_count: int
    most_called_tool: Optional[str] = None
    tool_call_counts: dict[str, int] = Field(default_factory=dict)


class SummaryRequest(BaseModel):
    document_id: str = Field(..., min_length=1, description="文档 ID")


class KeywordsRequest(BaseModel):
    document_id: str = Field(..., min_length=1, description="文档 ID")
    max_keywords: int = Field(default=10, ge=1, le=30, description="最多返回关键词数量")


class MetricsRequest(BaseModel):
    document_id: str = Field(..., min_length=1, description="文档 ID")
