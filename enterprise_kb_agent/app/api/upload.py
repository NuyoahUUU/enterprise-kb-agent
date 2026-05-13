import requests
from fastapi import APIRouter, File, Form, UploadFile

from app.core.config import settings
from app.schemas.document import DocumentItem, DocumentUploadData
from app.services.document_service import DocumentService
from app.utils.response import success_response


router = APIRouter(tags=["documents"])
document_service = DocumentService()


@router.post("/upload")
async def upload_document(file: UploadFile = File(...), library: str = Form(default="enterprise"),
                          overwrite: bool = Form(default=False)):
    data = await document_service.upload_document(file, library=library, overwrite=overwrite)
    return success_response(DocumentUploadData(**data).model_dump())


@router.get("/documents")
def list_documents(library: str = "enterprise"):
    documents = [DocumentItem(**item).model_dump() for item in document_service.list_documents(library)]
    return success_response({"documents": documents, "library": library})


@router.get("/documents/{document_id}/content")
def get_document_content(document_id: str, library: str = "enterprise"):
    text = document_service.get_document_text(document_id, library)
    metadata = document_service.get_document_metadata(document_id, library)
    return success_response({"document_id": document_id, "filename": metadata.get("filename", ""),
                             "content": text, "char_count": len(text)})


@router.delete("/documents/{document_id}")
def delete_document(document_id: str, library: str = "enterprise"):
    data = document_service.delete_document(document_id, library)
    return success_response(data)


@router.get("/models")
def list_models():
    """聚合所有可用模型：本地 Ollama + 云端 OpenAI-compatible 服务."""
    all_models: list[dict] = []
    current = ""

    # 1. 本地 Ollama 模型
    try:
        resp = requests.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags", timeout=3)
        resp.raise_for_status()
        for m in resp.json().get("models", []):
            all_models.append({"id": m["name"], "provider": "ollama", "label": m["name"]})
        if settings.llm_provider == "ollama":
            current = settings.ollama_model
    except Exception:
        # Ollama 不可用时仍保留配置中的模型作为备选
        all_models.append({"id": settings.ollama_model, "provider": "ollama", "label": settings.ollama_model})
        if settings.llm_provider == "ollama":
            current = settings.ollama_model

    # 2. DeepSeek 模型
    if settings.deepseek_api_key:
        try:
            resp = requests.get(
                f"{settings.deepseek_base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
                timeout=5,
            )
            resp.raise_for_status()
            for m in resp.json().get("data", []):
                mid = m["id"]
                if not any(x["id"] == mid for x in all_models):
                    all_models.append({"id": mid, "provider": "deepseek", "label": mid})
        except Exception:
            pass
        # 确保配置的模型在列表中
        if not any(x["id"] == settings.deepseek_model for x in all_models):
            all_models.append({"id": settings.deepseek_model, "provider": "deepseek", "label": settings.deepseek_model})
        if settings.llm_provider == "deepseek":
            current = settings.deepseek_model

    # 3. OpenAI 模型
    if settings.openai_api_key:
        if not any(x["id"] == settings.openai_model for x in all_models):
            all_models.append({"id": settings.openai_model, "provider": "openai", "label": settings.openai_model})
        if settings.llm_provider == "openai":
            current = settings.openai_model

    # 4. Qwen 模型
    if settings.qwen_api_key:
        if not any(x["id"] == settings.qwen_model for x in all_models):
            all_models.append({"id": settings.qwen_model, "provider": "qwen", "label": settings.qwen_model})
        if settings.llm_provider == "qwen":
            current = settings.qwen_model

    if not current and all_models:
        current = all_models[0]["id"]

    return success_response({"models": all_models, "current": current})
