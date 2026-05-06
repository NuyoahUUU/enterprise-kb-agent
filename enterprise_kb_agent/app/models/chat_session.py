from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.database import Base


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(64), index=True, nullable=False)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    document_id = Column(String(64), index=True, nullable=True)
    tool_name = Column(String(64), nullable=True)
    library = Column(String(32), default="enterprise", nullable=True)
    user_id = Column(Integer, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)

