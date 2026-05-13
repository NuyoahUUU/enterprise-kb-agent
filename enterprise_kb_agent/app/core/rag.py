import threading as _threading
from typing import Optional

from app.core.config import settings
from app.core.llm import LLMClient
from app.core.vectorstore import get_vectorstore_service


class RAGService:
    def __init__(self):
        self.vectorstore = get_vectorstore_service()
        self.llm = LLMClient()

    def add_document(self, document_id: str, filename: str, chunks: list, library: str = "enterprise") -> None:
        self.vectorstore.add_documents(document_id, filename, chunks, library=library)

    def search(self, query: str, document_id: Optional[str] = None, top_k: Optional[int] = None,
               library: str = "enterprise") -> list[dict]:
        return self.vectorstore.search(query, document_id=document_id, top_k=top_k, library=library)

    def get_document_chunks(self, document_id: str, library: str = "enterprise") -> list[dict]:
        return self.vectorstore.get_document_chunks(document_id, library=library)

    def delete_document(self, document_id: str, library: str = "enterprise") -> None:
        self.vectorstore.delete_document(document_id, library=library)

    def format_history(self, history: list[dict]) -> str:
        if not history:
            return "无"
        return "\n".join(f"{item['role']}: {item['content']}" for item in history[-settings.memory_window_size:])

    def format_sources_for_context(self, sources: list[dict]) -> str:
        if not sources:
            return "未检索到相关片段"
        lines = []
        for idx, source in enumerate(sources, start=1):
            page_text = f" | page {source['page']}" if source.get("page") else ""
            lines.append(
                f"[来源 {idx} | {source['filename']} | {source['chunk_id']}{page_text} | "
                f"score={source.get('similarity_score')}]\n{source.get('content', '')}"
            )
        return "\n\n".join(lines)

    def build_extractive_fallback(self, sources: list[dict]) -> str:
        if not sources:
            return "未检索到与问题相关的知识库片段，请先上传文档或调整问题。"
        filenames = ", ".join(dict.fromkeys(s for s in (s_.get("filename", "") for s_ in sources) if s))
        lines = [f"基于已检索到的知识库片段，{filenames or '当前文档'} 主要包含以下内容："]
        for idx, source in enumerate(sources[:3], start=1):
            lines.append(f"{idx}. {source['content_preview']}（来源：{source['filename']} / {source['chunk_id']}）")
        return "\n".join(lines)


_rag_service: RAGService | None = None
_rag_lock = _threading.Lock()


def get_rag_service() -> RAGService:
    global _rag_service
    if _rag_service is None:
        with _rag_lock:
            if _rag_service is None:
                _rag_service = RAGService()
    return _rag_service
