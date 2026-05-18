import json
import re
from collections import Counter
from typing import Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.core.llm import LLMClient


class KeywordExtractInput(BaseModel):
    text: Optional[str] = Field(default=None, description="待提取关键词的文本")
    document_id: Optional[str] = Field(default=None, description="可选，上传文档的 ID")
    max_keywords: int = Field(default=10, ge=1, le=30, description="最多返回关键词数量")


def keyword_extract_tool(
    text: str | None = None,
    document_id: str | None = None,
    max_keywords: int = 10,
) -> dict:
    """Extract keywords from a question, retrieved snippets, or an uploaded document."""

    source_text = text
    if not source_text and document_id:
        from app.services.document_service import DocumentService

        source_text = DocumentService().get_document_text(document_id)
    source_text = source_text or ""
    fallback = _fallback_keywords(source_text, max_keywords=max_keywords)
    if len(source_text) < 120:
        return {"document_id": document_id, "keywords": fallback}

    prompt = f"""
请从下面文本中提取最多 {max_keywords} 个关键词，输出严格 JSON：
{{"keywords": ["关键词1", "关键词2"]}}

文本：
{source_text[:12000]}
""".strip()
    llm = LLMClient()
    response = llm.generate(
        prompt,
        system_prompt="你是关键词提取工具，只输出可解析 JSON。",
        fallback_text=json.dumps({"keywords": fallback}, ensure_ascii=False),
    )
    parsed = llm.parse_json_from_text(response)
    keywords = fallback
    if isinstance(parsed, dict) and isinstance(parsed.get("keywords"), list):
        keywords = [str(item).strip() for item in parsed["keywords"] if str(item).strip()]
    elif isinstance(parsed, list):
        keywords = [str(item).strip() for item in parsed if str(item).strip()]
    return {"document_id": document_id, "keywords": keywords[:max_keywords]}


def build_keyword_extract_tool() -> StructuredTool:
    return StructuredTool.from_function(
        name="keyword_extract_tool",
        description="从用户问题、文档片段或整篇文档中提取关键词，适合关键词、主题词、检索词类问题。",
        func=keyword_extract_tool,
        args_schema=KeywordExtractInput,
    )


def _fallback_keywords(text: str, max_keywords: int) -> list[str]:
    stopwords = {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "are",
        "was",
        "were",
        "our",
        "their",
        "paper",
        "method",
        "result",
        "results",
        "using",
        "based",
        "企业",
        "知识库",
        "文档",
        "问题",
        "这个",
        "可以",
        "通过",
    }
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9+\-_/]{2,}|[\u4e00-\u9fff]{2,6}", text.lower())
    candidates = [token for token in tokens if token not in stopwords and not token.isdigit()]
    counter = Counter(candidates)
    return [word for word, _ in counter.most_common(max_keywords)]

