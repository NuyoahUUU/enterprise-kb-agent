import json
import re
from typing import Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.core.llm import LLMClient


class ExperimentMetricInput(BaseModel):
    document_id: Optional[str] = Field(default=None, description="可选，上传文档的 ID")
    content: Optional[str] = Field(default=None, description="可选，待分析的文档片段")


def experiment_metric_tool(document_id: str | None = None, content: str | None = None) -> dict:
    """Extract or simulate querying experiment/project metrics from knowledge documents."""

    text = content
    if not text and document_id:
        from app.services.document_service import DocumentService

        text = DocumentService().get_document_text(document_id)
    text = text or ""
    fallback = _fallback_metrics(text)
    prompt = f"""
请从下面内容中抽取项目指标、实验结果或数据表信息，关注 Accuracy、F1、mIoU、OA、Precision、Recall、AUC、mAP、耗时、成本等。
输出严格 JSON：
{{
  "metrics": [
    {{"metric": "Accuracy", "value": "95.1%", "context": "对应原文证据"}}
  ]
}}
如果没有找到，返回 {{"metrics": []}}。

内容：
{text[:18000]}
""".strip()
    llm = LLMClient()
    response = llm.generate(
        prompt,
        system_prompt="你是企业知识库指标查询工具，只输出可解析 JSON。",
        fallback_text=json.dumps({"metrics": fallback}, ensure_ascii=False),
    )
    parsed = llm.parse_json_from_text(response)
    metrics = fallback
    if isinstance(parsed, dict) and isinstance(parsed.get("metrics"), list):
        metrics = _normalize_metrics(parsed["metrics"])
    elif isinstance(parsed, list):
        metrics = _normalize_metrics(parsed)
    return {"document_id": document_id, "metrics": metrics}


def build_experiment_metric_tool() -> StructuredTool:
    return StructuredTool.from_function(
        name="experiment_metric_tool",
        description="查询或抽取企业知识库中的实验指标、项目指标、模型效果和数据表结果。",
        func=experiment_metric_tool,
        args_schema=ExperimentMetricInput,
    )


def _normalize_metrics(items: list) -> list[dict]:
    metrics = []
    for item in items:
        if not isinstance(item, dict):
            continue
        metric = str(item.get("metric", "")).strip()
        value = str(item.get("value", "")).strip()
        context = str(item.get("context", "")).strip()
        if metric and value:
            metrics.append({"metric": metric, "value": value, "context": context})
    return metrics


def _fallback_metrics(text: str) -> list[dict]:
    metric_pattern = (
        r"Accuracy|Acc|F1(?:-score)?|mIoU|Mean IoU|IoU|OA|Precision|Recall|AUC|mAP|AP|"
        r"准确率|精确率|召回率|响应时间|耗时|成本|命中率"
    )
    value_pattern = r"\d+(?:\.\d+)?\s*%|\d+\.\d+|\d+\s*(?:ms|s|秒|分钟|元|次)"
    metric_with_suffix = rf"(?:{metric_pattern})(?:@\d+)?"
    patterns = [
        re.compile(
            rf"(?P<metric>{metric_with_suffix})\s*(?:=|:|为|达到|is|of)?\s*(?P<value>{value_pattern})",
            re.I,
        ),
        re.compile(rf"(?P<value>{value_pattern})\s*(?P<metric>{metric_with_suffix})", re.I),
    ]

    metrics = []
    seen = set()
    for line in re.split(r"[\n。;]", text):
        context = line.strip()
        if not context:
            continue
        for pattern in patterns:
            for match in pattern.finditer(context):
                metric = match.group("metric").strip()
                value = re.sub(r"\s+", "", match.group("value").strip())
                key = (metric.lower(), value)
                if key in seen:
                    continue
                seen.add(key)
                metrics.append({"metric": metric, "value": value, "context": context[:300]})
    return metrics[:30]

