from pydantic import BaseModel


class DocumentUploadData(BaseModel):
    document_id: str
    filename: str
    chunk_count: int
    char_count: int


class DocumentItem(BaseModel):
    document_id: str
    filename: str
    chunk_count: int
    char_count: int
    created_at: str

