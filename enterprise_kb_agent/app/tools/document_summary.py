import json
import re
from typing import Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.core.llm import LLMClient


class DocumentSummaryInput(BaseModel):
    document_id: Optional[str] = Field(default=None, description="可选，上传文档的 ID")
    content: Optional[str] = Field(default=None, description="可选，检索片段或文档片段内容")
    query: Optional[str] = Field(default=None, description="用户原始问题")


def document_summary_tool(
    document_id: str | None = None,
    content: str | None = None,
    query: str | None = None,
) -> dict:
    """Summarize an uploaded document or retrieved snippets."""

    text = content
    if not text and document_id:
        from app.services.document_service import DocumentService

        text = DocumentService().get_document_text(document_id)
    if not text:
        return {
            "document_id": document_id,
            "summary": {},
            "answer": "未提供可总结的文档内容，请先上传文档或触发知识库检索。",
        }

    fallback = _fallback_summary(text)
    prompt = f"""
请基于下面的企业知识库内容生成结构化摘要。只输出严格 JSON，不要输出 Markdown。
JSON 字段必须为：
{{
  "background": "背景/业务问题",
  "key_points": "核心信息",
  "process": "流程/方法",
  "conclusion": "结论/建议"
}}

用户问题：{query or "总结文档"}

知识库内容：
{_clip_text(text)}
""".strip()
    llm = LLMClient()
    response = llm.generate(
        prompt,
        system_prompt="你是企业知识库摘要工具，只输出可解析 JSON。",
        fallback_text=json.dumps(fallback, ensure_ascii=False),
    )
    parsed = llm.parse_json_from_text(response)
    summary = _normalize_summary(parsed if isinstance(parsed, dict) else fallback)
    return {
        "document_id": document_id,
        "summary": summary,
        "answer": _format_summary_answer(summary),
    }


def build_document_summary_tool() -> StructuredTool:
    return StructuredTool.from_function(
        name="document_summary_tool",
        description="对上传文档或知识库检索片段进行摘要，适合回答总结、概括、核心观点类问题。",
        func=document_summary_tool,
        args_schema=DocumentSummaryInput,
    )


def _normalize_summary(data: dict) -> dict[str, str]:
    return {
        "background": str(data.get("background") or data.get("背景") or "").strip(),
        "key_points": str(data.get("key_points") or data.get("核心信息") or data.get("要点") or "").strip(),
        "process": str(data.get("process") or data.get("流程") or data.get("方法") or "").strip(),
        "conclusion": str(data.get("conclusion") or data.get("结论") or data.get("建议") or "").strip(),
    }


def _fallback_summary(text: str) -> dict[str, str]:
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()]
    head = "\n".join(paragraphs[:2]) if paragraphs else text
    middle = "\n".join(paragraphs[2:5]) if len(paragraphs) > 2 else head
    tail = paragraphs[-1] if paragraphs else text
    return {
        "background": head[:500],
        "key_points": middle[:700],
        "process": middle[:700],
        "conclusion": tail[:500],
    }


def _format_summary_answer(summary: dict[str, str]) -> str:
    return (
        f"背景/问题：{summary.get('background', '')}\n\n"
        f"核心信息：{summary.get('key_points', '')}\n\n"
        f"流程/方法：{summary.get('process', '')}\n\n"
        f"结论/建议：{summary.get('conclusion', '')}"
    )


def _clip_text(text: str, limit: int = 12000) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + "\n\n......中间内容省略......\n\n" + text[-half:]

