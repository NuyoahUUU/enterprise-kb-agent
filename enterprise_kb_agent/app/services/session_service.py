from uuid import uuid4

from app.database import session_scope
from app.models.chat_session import ChatMessage


class SessionService:
    def new_session_id(self) -> str:
        return uuid4().hex

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        document_id: str | None = None,
        tool_name: str | None = None,
        library: str = "enterprise",
    ) -> None:
        with session_scope() as db:
            db.add(
                ChatMessage(
                    session_id=session_id,
                    role=role,
                    content=content,
                    document_id=document_id,
                    tool_name=tool_name,
                    library=library,
                )
            )

    def get_history(self, session_id: str, limit: int = 10) -> list[dict]:
        with session_scope() as db:
            rows = (
                db.query(ChatMessage)
                .filter(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
                .limit(limit)
                .all()
            )
        rows = list(reversed(rows))
        return [
            {
                "role": row.role,
                "content": row.content,
                "document_id": row.document_id,
                "tool_name": row.tool_name,
                "library": row.library or "enterprise",
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]

    def list_sessions(self, limit: int = 50, library: str | None = None) -> list[dict]:
        with session_scope() as db:
            # 第一步：找到最近活跃的 N 个 session_id
            from sqlalchemy import func as sa_func
            base = db.query(
                ChatMessage.session_id,
                sa_func.max(ChatMessage.created_at).label("latest_ts"),
            ).group_by(ChatMessage.session_id)
            if library:
                base = base.filter(ChatMessage.library == library)
            top_sids = [row[0] for row in base.order_by(
                sa_func.max(ChatMessage.created_at).desc()
            ).limit(limit).all()]
            if not top_sids:
                return []

            # 第二步：只加载这些 session 的消息
            rows = (
                db.query(ChatMessage)
                .filter(ChatMessage.session_id.in_(top_sids))
                .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
                .all()
            )
        sessions: dict[str, dict] = {}
        for row in rows:
            session = sessions.setdefault(
                row.session_id,
                {
                    "session_id": row.session_id,
                    "message_count": 0,
                    "document_ids": [],
                    "tool_names": [],
                    "question": "",
                    "library": row.library or "enterprise",
                    "updated_at": row.created_at.isoformat(),
                },
            )
            session["message_count"] += 1
            if row.role == "user":
                session["question"] = row.content
            if row.document_id and row.document_id not in session["document_ids"]:
                session["document_ids"].append(row.document_id)
            if row.tool_name and row.tool_name not in session["tool_names"]:
                session["tool_names"].append(row.tool_name)
        return sorted(sessions.values(), key=lambda s: s["updated_at"], reverse=True)[:limit]

    def delete_session(self, session_id: str) -> int:
        with session_scope() as db:
            count = (
                db.query(ChatMessage)
                .filter(ChatMessage.session_id == session_id)
                .delete()
            )
        return count
