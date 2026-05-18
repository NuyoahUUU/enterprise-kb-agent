from app.services.document_service import DocumentService
from app.tools.document_summary import document_summary_tool
from app.tools.experiment_metric import experiment_metric_tool
from app.tools.keyword_extract import keyword_extract_tool


class ToolService:
    """Backward-compatible facade over the canonical core StructuredTool functions."""

    def __init__(self):
        self.document_service = DocumentService()

    def summarize_document(self, document_id: str) -> dict:
        return document_summary_tool(document_id=document_id)

    def extract_keywords(self, document_id: str, max_keywords: int = 10) -> dict:
        return keyword_extract_tool(document_id=document_id, max_keywords=max_keywords)

    def extract_metrics(self, document_id: str) -> dict:
        return experiment_metric_tool(document_id=document_id)
