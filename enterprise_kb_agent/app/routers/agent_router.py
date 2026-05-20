from fastapi import APIRouter

from app.core.agent import get_agent_service
from app.schemas.request import ChatRequest, KeywordsRequest, MetricsRequest, SummaryRequest
from app.schemas.response import (
    ChatData,
    KeywordsData,
    MetricsData,
    SessionHistoryData,
    SessionListData,
    SummaryData,
)
from app.services.session_service import SessionService
from app.services.tool_service import ToolService
from app.utils.response import success_response


router = APIRouter(prefix="/api/agent", tags=["agent"])
session_service = SessionService()
tool_service = ToolService()


@router.post("/chat")
def chat(request: ChatRequest):
    data = get_agent_service().run(
        question=request.question,
        session_id=request.session_id,
        document_id=request.document_id,
        top_k=request.top_k,
        model=request.model,
        provider=request.provider,
        library=request.library,
        permission_mode=request.permission_mode,
    )
    return success_response(ChatData(**data).model_dump())


@router.post("/summary")
def summarize_document(request: SummaryRequest):
    result = tool_service.summarize_document(request.document_id)
    return success_response(SummaryData(**result).model_dump())


@router.post("/keywords")
def extract_keywords(request: KeywordsRequest):
    result = tool_service.extract_keywords(request.document_id, max_keywords=request.max_keywords)
    return success_response(KeywordsData(**result).model_dump())


@router.post("/metrics")
def extract_metrics(request: MetricsRequest):
    result = tool_service.extract_metrics(request.document_id)
    return success_response(MetricsData(**result).model_dump())


@router.get("/sessions")
def list_sessions(limit: int = 50, library: str | None = None):
    documents = {
        item["document_id"]: item["filename"]
        for item in tool_service.document_service.list_documents(library=library or "enterprise")
    }
    sessions = []
    for session in session_service.list_sessions(limit=limit, library=library):
        sessions.append(
            {
                "session_id": session["session_id"],
                "documents": [
                    {
                        "document_id": document_id,
                        "filename": documents.get(document_id),
                    }
                    for document_id in session["document_ids"]
                ],
                "message_count": session["message_count"],
                "tool_names": session["tool_names"],
                "question": session["question"][:80],
                "library": session.get("library", "enterprise"),
                "updated_at": session["updated_at"],
            }
        )
    return success_response(SessionListData(sessions=sessions).model_dump())


@router.get("/sessions/{session_id}/history")
def get_session_history(session_id: str, limit: int = 20):
    history = session_service.get_history(session_id=session_id, limit=limit)
    return success_response(SessionHistoryData(session_id=session_id, messages=history).model_dump())


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str):
    count = session_service.delete_session(session_id)
    return success_response({"session_id": session_id, "deleted_messages": count})
