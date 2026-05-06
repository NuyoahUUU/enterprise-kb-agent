import threading as _threading

from app.core.config import settings
from app.services.session_service import SessionService


class ConversationMemoryStore:
    """DB-backed session memory for recent multi-turn chat context."""

    def __init__(self):
        self._session_service = SessionService()

    def new_session_id(self) -> str:
        return self._session_service.new_session_id()

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        document_id: str | None = None,
        tool_name: str | None = None,
        library: str = "enterprise",
    ) -> None:
        self._session_service.add_message(
            session_id=session_id,
            role=role,
            content=content,
            document_id=document_id,
            tool_name=tool_name,
            library=library,
        )

    def get_history(self, session_id: str, limit: int | None = None) -> list[dict]:
        return self._session_service.get_history(
            session_id=session_id,
            limit=limit or settings.memory_window_size * 2,
        )


_memory_store: ConversationMemoryStore | None = None
_mem_lock = _threading.Lock()


def get_memory_store() -> ConversationMemoryStore:
    global _memory_store
    if _memory_store is None:
        with _mem_lock:
            if _memory_store is None:
                _memory_store = ConversationMemoryStore()
    return _memory_store
