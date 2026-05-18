from typing import Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.core.vectorstore import get_vectorstore_service


class KnowledgeSearchInput(BaseModel):
    query: str = Field(..., description="用户问题或改写后的完整检索问题")
    document_id: Optional[str] = Field(default=None, description="可选，限定某个文档内检索")
    top_k: int = Field(default=4, ge=1, le=10, description="返回的相关片段数量")


def knowledge_search_tool(query: str, document_id: str | None = None, top_k: int = 4) -> dict:
    """Search enterprise knowledge base chunks from ChromaDB."""

    sources = get_vectorstore_service().search(query=query, document_id=document_id, top_k=top_k)
    return {
        "query": query,
        "hit_count": len(sources),
        "sources": sources,
    }


def build_knowledge_search_tool() -> StructuredTool:
    return StructuredTool.from_function(
        name="knowledge_search_tool",
        description="从企业知识库 ChromaDB 中检索与问题最相关的文档片段，返回来源、chunk、相似度和内容预览。",
        func=knowledge_search_tool,
        args_schema=KnowledgeSearchInput,
    )

