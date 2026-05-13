from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.core.agent import get_agent_service
from app.schemas.chat import ChatRequest, ChatResponseData
from app.utils.response import success_response


router = APIRouter(tags=["chat"])


@router.post("/chat")
def chat(request: ChatRequest):
    data = get_agent_service().run(
        question=request.question, session_id=request.session_id,
        document_id=request.document_id, model=request.model, provider=request.provider,
        library=request.library, top_k=request.top_k, permission_mode=request.permission_mode,
    )
    return success_response(ChatResponseData(**data).model_dump())


@router.post("/chat/stream")
def stream_chat(request: ChatRequest):
    stream = get_agent_service().run_stream(
        question=request.question, session_id=request.session_id,
        document_id=request.document_id, model=request.model, provider=request.provider,
        library=request.library, top_k=request.top_k, permission_mode=request.permission_mode,
    )
    return StreamingResponse(stream, media_type="text/event-stream")
