from fastapi import APIRouter, File, UploadFile

from app.schemas.response import DocumentItem, DocumentUploadData
from app.services.document_service import DocumentService
from app.utils.response import success_response


router = APIRouter(prefix="/api/documents", tags=["documents"])
document_service = DocumentService()


@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    data = await document_service.upload_document(file)
    return success_response(DocumentUploadData(**data).model_dump())


@router.get("/list")
def list_documents():
    documents = [DocumentItem(**item).model_dump() for item in document_service.list_documents()]
    return success_response({"documents": documents})
