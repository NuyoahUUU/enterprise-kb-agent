import json
import logging
import re
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Generator, Optional

import numpy as np
import requests

from app.core.config import settings
from app.core.llm import LLMClient
from app.core.logger import get_query_logger
from app.core.memory import get_memory_store
from app.core.rag import get_rag_service
from app.services.operation_service import OperationService
from app.tools.host_commands import run_command, read_file, write_file

logger = logging.getLogger(__name__)

# 共享 Embedding 模型，避免重复加载导致 OOM
_shared_embedding_model = None
_shared_embedding_lock = threading.Lock()


def _get_shared_embedding_model():
    """懒加载共享的 SentenceTransformer 模型（线程安全）。"""
    global _shared_embedding_model
    if _shared_embedding_model is not None:
        return _shared_embedding_model
    with _shared_embedding_lock:
        if _shared_embedding_model is not None:
            return _shared_embedding_model
        try:
            from sentence_transformers import SentenceTransformer as ST
            _shared_embedding_model = ST(settings.embedding_model_name)
            logger.info("Shared embedding model loaded: %s", settings.embedding_model_name)
        except Exception:
            logger.warning("Failed to load shared embedding model; skill matching disabled.")
            _shared_embedding_model = False  # sentinel to avoid retry
        return _shared_embedding_model


SKILL_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "skills" / "skill_registry.json"
WORKSPACE_ROOT = str(Path(__file__).resolve().parents[2])

REACT_SYSTEM_PROMPT = """你是企业知识库 Agent。你可以检索知识库、总结文档、抽取关键词和指标，并基于来源回答用户问题。

知识库工具：
- knowledge_search(query, document_id?, top_k?) — 检索文档（遇到问题先查文档）
- summarize_document(document_id) — 摘要文档
- extract_keywords(document_id) — 提取关键词
- extract_metrics(document_id) — 提取实验指标

宿主操作工具（仅非 read_only 模式可用）：
- run_command(command, cwd?, timeout_seconds?) — 在用户机器上执行 shell 命令（非交互式，仅返回 stdout/stderr）
- read_file(file_path, offset?, limit?) — 读取用户机器上的文件内容，或列出目录
- write_file(file_path, content, append?) — 将内容写入用户机器上的文件

工作方式：
1. 用户提出任务 → 先查知识库找参考文档
2. 根据问题选择摘要、关键词或指标工具
3. 基于检索片段、工具观察结果和历史对话回答
4. 回答中尽量说明依据来自哪些文档或片段
5. 当用户要求执行本地操作时（如"帮我看看 ~/.zshrc"、"执行 git status"、"写一个脚本"），使用宿主操作工具

安全规则：
- 只有用户明确要求时才使用宿主操作工具
- 执行命令前先确认不会造成破坏
- 读写文件仅限于用户目录和项目目录
- 不做超出用户请求范围的操作
- 不编造未检索到的文档内容
"""

TOOL_SCHEMAS = [
    {"type": "function", "function": {"name": "knowledge_search", "description": "从企业知识库 ChromaDB 中检索相关文档片段",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "检索查询"},
            "document_id": {"type": "string", "description": "可选，限定文档 ID"},
            "top_k": {"type": "integer", "description": "返回数量，默认 4"}},
        "required": ["query"]}}},
    {"type": "function", "function": {"name": "summarize_document", "description": "对指定文档进行摘要总结",
        "parameters": {"type": "object", "properties": {
            "document_id": {"type": "string", "description": "文档 ID"},
            "query": {"type": "string", "description": "可选，摘要着重方向"}},
        "required": ["document_id"]}}},
    {"type": "function", "function": {"name": "extract_keywords", "description": "从文档中提取关键词",
        "parameters": {"type": "object", "properties": {
            "document_id": {"type": "string", "description": "文档 ID"},
            "text": {"type": "string", "description": "可选，待提取文本"},
            "max_keywords": {"type": "integer", "description": "最多关键词数，默认 10"}},
        "required": ["document_id"]}}},
    {"type": "function", "function": {"name": "extract_metrics", "description": "从文档中提取实验指标（accuracy, f1, precision, recall, miou 等）",
        "parameters": {"type": "object", "properties": {
            "document_id": {"type": "string", "description": "文档 ID"},
            "content": {"type": "string", "description": "可选，待分析文本"}},
        "required": ["document_id"]}}},
    {"type": "function", "function": {"name": "run_command", "description": "在用户机器上执行 shell 命令并返回 stdout/stderr。非交互式，有超时限制。仅在用户明确要求执行本地命令时使用。",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "description": "要执行的 shell 命令，如 git status、ls -la、python --version"},
            "cwd": {"type": "string", "description": "工作目录，默认为项目根目录"},
            "timeout_seconds": {"type": "integer", "description": "超时秒数，默认 120"}},
        "required": ["command"]}}},
    {"type": "function", "function": {"name": "read_file", "description": "读取用户机器上的文件内容，或列出目录下的文件。仅在用户要求查看文件或目录时使用。",
        "parameters": {"type": "object", "properties": {
            "file_path": {"type": "string", "description": "文件或目录的绝对路径，如 /Users/xxx/.zshrc 或 /Users/xxx/projects"},
            "offset": {"type": "integer", "description": "起始行号（0-indexed），默认从第一行开始"},
            "limit": {"type": "integer", "description": "最多读取行数，默认读取全部"}},
        "required": ["file_path"]}}},
    {"type": "function", "function": {"name": "write_file", "description": "将内容写入用户机器上的文件（创建或覆盖）。仅在用户明确要求创建/修改文件时使用。",
        "parameters": {"type": "object", "properties": {
            "file_path": {"type": "string", "description": "要写入的文件绝对路径"},
            "content": {"type": "string", "description": "要写入的文件内容"},
            "append": {"type": "boolean", "description": "是否追加到文件末尾（默认 false，即覆盖写入）"}},
        "required": ["file_path", "content"]}}},
]


class ReActAgent:
    """ReAct Agent：思考 → 并行工具调用 → 观察 → 重试 → 循环."""

    MAX_ITERATIONS = 15
    MAX_RETRIES = 2

    def __init__(self):
        self.memory = get_memory_store()
        self.logger = get_query_logger()
        self.rag = get_rag_service()
        self.llm = LLMClient()
        self.operations = OperationService()
        self._skills = []
        self._skill_texts = []
        self._skill_embeddings = None

    # ── Skill 系统 ────────────────────────────────────────

    def _load_skills(self):
        """加载 skill 注册表并构建向量."""
        if not SKILL_REGISTRY_PATH.exists():
            return
        with open(SKILL_REGISTRY_PATH, encoding="utf-8") as f:
            self._skills = json.load(f)
        # 每个 skill 的描述 + 关键词 作为匹配文本
        self._skill_texts = [
            f"{s['description']} {' '.join(s.get('keywords', []))}"
            for s in self._skills
        ]
        if self._skill_texts:
            model = _get_shared_embedding_model()
            if model and model is not False:
                try:
                    self._skill_embeddings = model.encode(self._skill_texts, normalize_embeddings=True)
                except Exception:
                    self._skill_embeddings = None
            else:
                self._skill_embeddings = None

    def _match_skills(self, question: str, top_k: int = 2) -> list[dict]:
        """用问题向量匹配最相关的 skill，返回 skill 内容."""
        if not self._skills or self._skill_embeddings is None:
            return []
        model = _get_shared_embedding_model()
        if not model or model is False:
            return []
        try:
            q_emb = model.encode([question], normalize_embeddings=True)[0]
        except Exception:
            return []
        scores = np.dot(self._skill_embeddings, q_emb)
        top_indices = np.argsort(scores)[-top_k:][::-1]
        matched = []
        for idx in top_indices:
            if scores[idx] < 0.3:  # 相似度太低跳过
                continue
            skill = self._skills[idx]
            # 加载 skill 对应文档的完整内容
            doc_path = Path(WORKSPACE_ROOT) / "examples" / skill["doc"]
            content = ""
            if doc_path.exists():
                content = doc_path.read_text(encoding="utf-8")[:2000]
            matched.append({
                "name": skill["name"],
                "description": skill["description"],
                "score": float(scores[idx]),
                "content": content,
            })
        return matched

    # ── 工具注册 ─────────────────────────────────────────

    @property
    def tools(self):
        return {
            "knowledge_search": self._tool_search,
            "summarize_document": self._tool_summarize,
            "extract_keywords": self._tool_keywords,
            "extract_metrics": self._tool_metrics,
            "run_command": self._tool_run_command,
            "read_file": self._tool_read_file,
            "write_file": self._tool_write_file,
        }

    def _tool_search(self, library: str = "enterprise", **kwargs) -> str:
        query = kwargs.get("query", "")
        document_id = kwargs.get("document_id")
        top_k = kwargs.get("top_k", 4)
        sources = self.rag.search(query=query, document_id=document_id, top_k=top_k, library=library)
        if not sources:
            return "未检索到相关文档片段。尝试换一个查询词或去掉 document_id 限制。"
        lines = [f"检索到 {len(sources)} 个相关片段："]
        for i, s in enumerate(sources, 1):
            lines.append(
                f"[{i}] {s['filename']} | {s['chunk_id']} | score={s.get('similarity_score', 'N/A')}\n"
                f"内容预览：{s.get('content_preview', '')}"
            )
        return "\n\n".join(lines)

    def _tool_summarize(self, library: str = "enterprise", **kwargs) -> str:
        document_id = kwargs.get("document_id", "")
        try:
            text = self.rag.vectorstore.get_document_chunks(document_id, library=library)
            if not text:
                return f"未找到 document_id={document_id} 的文档。请确认 document_id 正确（可从 knowledge_search 结果中获取）。"
            content = "\n".join(c.get("content", "") for c in text[:10])
            return f"文档 {document_id} 包含 {len(text)} 个片段：\n{content[:1500]}"
        except Exception as e:
            return f"摘要失败：{e}"

    def _tool_keywords(self, library: str = "enterprise", **kwargs) -> str:
        document_id = kwargs.get("document_id", "")
        text = kwargs.get("text", "")
        max_kw = kwargs.get("max_keywords", 10)
        try:
            chunks = self.rag.vectorstore.get_document_chunks(document_id, library=library)
            content = text or "\n".join(c.get("content", "") for c in chunks[:5])
            words = re.findall(r"[一-鿿]{2,}|[a-zA-Z]{3,}", content)
            top = Counter(words).most_common(max_kw)
            return "关键词：" + "、".join(w for w, _ in top)
        except Exception as e:
            return f"提取关键词失败：{e}"

    def _tool_metrics(self, library: str = "enterprise", **kwargs) -> str:
        document_id = kwargs.get("document_id", "")
        content = kwargs.get("content", "")
        try:
            chunks = self.rag.vectorstore.get_document_chunks(document_id, library=library)
            text = content or "\n".join(c.get("content", "") for c in chunks[:10])
            patterns = {
                "accuracy": r"(?:accuracy|acc|准确率|OA)\s*[:：=]?\s*([\d.]+)",
                "f1": r"(?:F1|f1)[- ]?(?:score)?\s*[:：=]?\s*([\d.]+)",
                "precision": r"(?:precision|精确率)\s*[:：=]?\s*([\d.]+)",
                "recall": r"(?:recall|召回率)\s*[:：=]?\s*([\d.]+)",
                "miou": r"(?:mIoU|miou|MIoU)\s*[:：=]?\s*([\d.]+)",
            }
            found = {}
            for name, pattern in patterns.items():
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    found[name] = match.group(1)
            if not found:
                return f"未在文档 {document_id} 中找到明确的实验指标。可尝试先用 knowledge_search 找到包含实验数据的文档。"
            lines = ["提取到的指标："]
            for k, v in found.items():
                lines.append(f"- {k}: {v}")
            return "\n".join(lines)
        except Exception as e:
            return f"提取指标失败：{e}"

    def _tool_run_command(self, library: str = "enterprise", permission_mode: str = "read_only", **kwargs) -> str:
        if permission_mode == "read_only":
            return json.dumps({"error": "当前为只读模式，不支持执行命令。请切换到非只读模式。",
                               "hint": "设置 permission_mode 为 approve_execute 以启用宿主操作。"},
                              ensure_ascii=False)
        command = kwargs.get("command", "")
        cwd = kwargs.get("cwd")
        timeout_seconds = kwargs.get("timeout_seconds", 120)
        if not command:
            return json.dumps({"error": "缺少 command 参数"}, ensure_ascii=False)
        logger.info("执行宿主命令: %s (cwd=%s)", command, cwd)
        result = run_command(command=command, cwd=cwd, timeout_seconds=timeout_seconds)
        return json.dumps(result, ensure_ascii=False)

    def _tool_read_file(self, library: str = "enterprise", permission_mode: str = "read_only", **kwargs) -> str:
        file_path = kwargs.get("file_path", "")
        offset = kwargs.get("offset", 0)
        limit = kwargs.get("limit")
        if not file_path:
            return json.dumps({"error": "缺少 file_path 参数"}, ensure_ascii=False)
        logger.info("读取宿主文件: %s", file_path)
        result = read_file(file_path=file_path, offset=offset, limit=limit)
        return json.dumps(result, ensure_ascii=False)

    def _tool_write_file(self, library: str = "enterprise", permission_mode: str = "read_only", **kwargs) -> str:
        if permission_mode == "read_only":
            return json.dumps({"error": "当前为只读模式，不支持写入文件。请切换到非只读模式。",
                               "hint": "设置 permission_mode 为 approve_execute 以启用宿主操作。"},
                              ensure_ascii=False)
        file_path = kwargs.get("file_path", "")
        content = kwargs.get("content", "")
        append = kwargs.get("append", False)
        if not file_path:
            return json.dumps({"error": "缺少 file_path 参数"}, ensure_ascii=False)
        logger.info("写入宿主文件: %s (append=%s)", file_path, append)
        result = write_file(file_path=file_path, content=content, append=append)
        return json.dumps(result, ensure_ascii=False)

    def _build_messages(self, question: str, history: list[dict], library: str = "enterprise") -> list[dict]:
        # 匹配相关 skill 并注入 system prompt
        skills = self._match_skills(question)
        skill_text = ""
        if skills:
            skill_text = "\n\n=== 已激活的操作指南（Skill） ===\n"
            for s in skills:
                skill_text += f"\n--- {s['name']} (匹配度: {s['score']:.2f}) ---\n{s['content']}\n"
        system_content = REACT_SYSTEM_PROMPT + skill_text

        msg_limit = max(settings.memory_window_size, 6)
        messages = [{"role": "system", "content": system_content}]
        for h in history[-msg_limit:]:
            role = "assistant" if h["role"] == "assistant" else "user"
            messages.append({"role": role, "content": h["content"]})
        messages.append({"role": "user", "content": question})
        return messages

    def _build_plan_prompt(self, question: str, history: list[dict]) -> list[dict]:
        """用于"先思考再行动"的规划阶段."""
        history_text = "\n".join(
            f"{h['role']}: {h['content'][:200]}" for h in history[-4:]
        ) if history else "无"
        return [
            {"role": "system", "content": "你是一个分析助手。在采取行动之前，先分析用户的问题并制定计划。"
                "请用中文简要说明：1）用户想要什么 2）需要哪些信息 3）计划用什么步骤来获取。50-100 字即可。"},
            {"role": "user", "content": f"历史对话：\n{history_text}\n\n用户问题：{question}\n\n请给出你的分析计划："},
        ]

    def _get_config_for_provider(self, provider: str) -> dict:
        """根据 provider 名获取对应的 API 配置."""
        if provider == "deepseek":
            return {"api_key": settings.deepseek_api_key, "base_url": settings.deepseek_base_url, "model": settings.deepseek_model}
        elif provider == "openai":
            return {"api_key": settings.openai_api_key, "base_url": settings.openai_base_url, "model": settings.openai_model}
        elif provider == "qwen":
            return {"api_key": settings.qwen_api_key, "base_url": settings.qwen_base_url, "model": settings.qwen_model}
        return self.llm._get_openai_compatible_config()

    def _call_llm(self, messages: list[dict], tools: bool = True, model: str | None = None,
                  provider: str | None = None) -> dict:
        provider = provider or settings.llm_provider
        if provider == "ollama":
            return self._call_ollama_chat(messages=messages, tools=tools, model=model)

        provider_config = self._get_config_for_provider(provider)
        api_key = provider_config["api_key"]
        base_url = provider_config["base_url"].rstrip("/")
        llm_model = model or provider_config["model"]

        payload = {"model": llm_model, "messages": messages, "temperature": 0.2, "max_tokens": 2048}
        if tools:
            payload["tools"] = TOOL_SCHEMAS

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        resp = requests.post(f"{base_url}/chat/completions", headers=headers, data=body, timeout=settings.llm_timeout)
        if not resp.ok:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text[:500]
            raise RuntimeError(f"API {resp.status_code}: {detail}")
        return self._normalize_llm_response(resp.json())

    def _call_ollama_chat(self, messages: list[dict], tools: bool = True, model: str | None = None) -> dict:
        payload = {
            "model": model or settings.ollama_model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": settings.llm_temperature,
                "num_predict": settings.ollama_num_predict,
            },
        }
        if tools:
            payload["tools"] = TOOL_SCHEMAS

        resp = requests.post(
            f"{settings.ollama_base_url.rstrip('/')}/api/chat",
            json=payload,
            timeout=settings.llm_timeout,
        )
        if not resp.ok:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text[:500]
            raise RuntimeError(f"Ollama API {resp.status_code}: {detail}")

        data = resp.json()
        message = data.get("message", {})
        return self._normalize_llm_response({"choices": [{"message": message}]})

    def _normalize_llm_response(self, data: dict) -> dict:
        choices = data.get("choices") or []
        if not choices:
            return data
        message = choices[0].get("message") or {}
        tool_calls = message.get("tool_calls") or []
        normalized = []
        for idx, tool_call in enumerate(tool_calls):
            function = tool_call.get("function", {})
            arguments = function.get("arguments", {})
            if not isinstance(arguments, str):
                arguments = json.dumps(arguments or {}, ensure_ascii=False)
            normalized.append(
                {
                    "id": tool_call.get("id") or f"tool_call_{idx}",
                    "type": tool_call.get("type", "function"),
                    "function": {
                        "name": function.get("name", ""),
                        "arguments": arguments,
                    },
                }
            )
        message["tool_calls"] = normalized
        choices[0]["message"] = message
        return data

    # ── 流式 LLM 调用 ─────────────────────────────────────

    def _call_llm_stream(self, messages: list[dict], tools: bool = False,
                         model: str | None = None,
                         provider: str | None = None) -> Generator[str, None, None]:
        """流式调用 LLM，逐 token yield。仅在已知不需要 tool_calls 时使用。"""
        provider = provider or settings.llm_provider
        if provider == "ollama":
            yield from self._call_ollama_chat_stream(messages=messages, model=model)
            return

        provider_config = self._get_config_for_provider(provider)
        api_key = provider_config["api_key"]
        base_url = provider_config["base_url"].rstrip("/")
        llm_model = model or provider_config["model"]

        payload = {"model": llm_model, "messages": messages, "temperature": 0.2, "max_tokens": 2048, "stream": True}
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        resp = requests.post(f"{base_url}/chat/completions", headers=headers, data=body,
                            timeout=settings.llm_timeout, stream=True)
        if not resp.ok:
            raise RuntimeError(f"API {resp.status_code}: {resp.text[:500]}")
        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            payload_text = line.removeprefix("data:").strip()
            if payload_text == "[DONE]":
                break
            try:
                token = json.loads(payload_text)["choices"][0].get("delta", {}).get("content")
                if token:
                    yield token
            except (json.JSONDecodeError, KeyError, IndexError):
                continue

    def _call_ollama_chat_stream(self, messages: list[dict], model: str | None = None) -> Generator[str, None, None]:
        """Ollama /api/chat 流式调用."""
        payload = {
            "model": model or settings.ollama_model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": settings.llm_temperature,
                "num_predict": settings.ollama_num_predict,
            },
        }
        resp = requests.post(
            f"{settings.ollama_base_url.rstrip('/')}/api/chat",
            json=payload,
            timeout=settings.llm_timeout,
            stream=True,
        )
        if not resp.ok:
            raise RuntimeError(f"Ollama API {resp.status_code}: {resp.text[:500]}")
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                data = json.loads(line)
                token = data.get("message", {}).get("content", "")
                if token:
                    yield token
                if data.get("done"):
                    break
            except json.JSONDecodeError:
                continue

    # ── main loop ─────────────────────────────────────────

    def run(self, question: str, session_id: str | None = None, document_id: str | None = None,
            model: str | None = None, provider: str | None = None, library: str = "enterprise",
            top_k: int | None = None, permission_mode: str = "read_only") -> dict:
        started_at = time.perf_counter()
        top_k = top_k or settings.default_top_k
        session_id = session_id or self.memory.new_session_id()
        history = self.memory.get_history(session_id, limit=settings.memory_window_size)
        operation_request = self.operations.build_proposal(question, permission_mode=permission_mode)
        if operation_request:
            final_answer = self._operation_answer(operation_request)
            self._save(session_id, question, final_answer, document_id, ["operation_proposal"], [], started_at, library=library)
            return {
                "session_id": session_id,
                "answer": final_answer,
                "sources": [],
                "tools": ["operation_proposal"],
                "iterations": 0,
                "operation_request": operation_request,
            }

        messages = self._build_messages(question, history, library=library)
        all_sources, tool_calls_made = [], []
        iterations, final_answer = 0, ""

        while iterations < self.MAX_ITERATIONS:
            iterations += 1
            try:
                response = self._call_llm(messages, model=model, provider=provider)
            except Exception as e:
                final_answer = self._build_llm_failure_fallback(
                    question=question,
                    document_id=document_id,
                    top_k=top_k,
                    library=library,
                    exc=e,
                    all_sources=all_sources,
                    tool_calls_made=tool_calls_made,
                )
                break

            msg = response["choices"][0]["message"]

            if msg.get("tool_calls"):
                messages.append(msg)
                results = self._execute_parallel(
                    msg["tool_calls"], question, document_id, tool_calls_made, all_sources,
                    top_k=top_k, library=library, permission_mode=permission_mode,
                )
                for tc, result, _is_error in results:
                    messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
                continue

            final_answer = msg.get("content", "") or str(msg)
            break

        if not final_answer and tool_calls_made:
            # 达到上限但工具已执行完毕，让 LLM 总结
            messages.append({"role": "user", "content": "以上工具已全部执行完毕。请用中文总结完成了哪些操作，以及最终结果。"})
            try:
                summary_resp = self._call_llm(messages[-8:], tools=False, model=model, provider=provider)
                final_answer = summary_resp["choices"][0]["message"].get("content", "")
            except Exception:
                final_answer = f"Agent 已执行 {len(tool_calls_made)} 个操作但未生成总结：{', '.join(tool_calls_made)}"

        self._save(session_id, question, final_answer, document_id, tool_calls_made, all_sources, started_at, library=library)
        return {"session_id": session_id, "answer": final_answer, "sources": self._public_sources(all_sources),
                "tools": tool_calls_made, "iterations": iterations}

    def run_stream(self, question: str, session_id: str | None = None, document_id: str | None = None,
                   model: str | None = None, provider: str | None = None, library: str = "enterprise",
                   top_k: int | None = None, permission_mode: str = "read_only") -> Generator[str, None, None]:
        started_at = time.perf_counter()
        top_k = top_k or settings.default_top_k
        session_id = session_id or self.memory.new_session_id()
        history = self.memory.get_history(session_id, limit=settings.memory_window_size)

        yield self._sse("meta", {"session_id": session_id, "mode": "react"})
        operation_request = self.operations.build_proposal(question, permission_mode=permission_mode)
        if operation_request:
            final_answer = self._operation_answer(operation_request)
            yield self._sse("operation", operation_request)
            yield self._sse("tools_done", {"tools": ["operation_proposal"], "iterations": 0})
            yield self._sse("token", {"token": final_answer, "kind": "response"})
            yield self._sse("done", {"session_id": session_id, "iterations": 0})
            self._save(session_id, question, final_answer, document_id, ["operation_proposal"], [], started_at, library=library)
            return

        # ── 阶段 1：Skill 匹配 + 思考规划 ──
        skills = self._match_skills(question)
        if skills:
            skill_names = ", ".join(f"{s['name']}({s['score']:.2f})" for s in skills)
            yield self._sse("thought", {"text": f"已激活 Skill: {skill_names}", "phase": "skill"})
        yield self._sse("agent_status", {"status": "planning", "text": "Agent 正在分析问题..."})
        plan_text = ""
        try:
            plan_msgs = self._build_plan_prompt(question, history)
            for token in self._call_llm_stream(plan_msgs, tools=False, model=model, provider=provider):
                plan_text += token
                yield self._sse("thought_token", {"token": token, "phase": "plan"})
            yield self._sse("thought", {"text": plan_text, "phase": "plan"})
        except Exception:
            yield self._sse("thought", {"text": "跳过规划阶段，直接执行。", "phase": "plan"})

        # ── 阶段 2：ReAct 循环 ──
        messages = self._build_messages(question, history, library=library)
        all_sources, tool_calls_made = [], []
        iterations, final_answer = 0, ""

        while iterations < self.MAX_ITERATIONS:
            iterations += 1
            yield self._sse("agent_status", {"status": "thinking", "iteration": iterations, "text": f"第 {iterations} 轮思考"})

            try:
                response = self._call_llm(messages, model=model, provider=provider)
            except Exception as e:
                error_msg = f"API 调用失败（第 {iterations} 轮）：{e}"
                yield self._sse("error_detail", {"message": error_msg})
                if iterations <= 2:
                    yield self._sse("thought", {"text": f"遇到错误，正在重试: {e}", "phase": "retry"})
                    continue
                final_answer = self._build_llm_failure_fallback(
                    question=question,
                    document_id=document_id,
                    top_k=top_k,
                    library=library,
                    exc=e,
                    all_sources=all_sources,
                    tool_calls_made=tool_calls_made,
                )
                yield self._sse("sources", {"sources": self._public_sources(all_sources)})
                yield self._sse("token", {"token": final_answer, "kind": "response"})
                break

            msg = response["choices"][0]["message"]

            if msg.get("tool_calls"):
                messages.append(msg)

                # 并行执行所有工具
                results = self._execute_parallel(
                    msg["tool_calls"], question, document_id, tool_calls_made, all_sources,
                    stream_callback=None, top_k=top_k, library=library, permission_mode=permission_mode,
                )

                # 流式通知每个工具的结果
                for tc, result, is_error in results:
                    func_name = tc["function"]["name"]
                    func_args = self._tool_args(tc)
                    yield self._sse("tool_call", {"tool": func_name, "args": func_args, "iteration": iterations})
                    trim = 180
                    summary = (result[:trim] + "...") if len(result) > trim else result
                    yield self._sse("tool_result", {"tool": func_name, "summary": summary, "error": is_error})

                    # 重试逻辑：如果工具失败，在消息中提示 LLM
                    if is_error and iterations <= self.MAX_RETRIES + 1:
                        yield self._sse("thought", {"text": f"工具 {func_name} 执行出错，将错误信息反馈给 Agent 重试", "phase": "retry"})

                    messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
                continue

            # LLM 给出最终答案
            final_answer = msg.get("content", "") or str(msg)
            yield self._sse("sources", {"sources": self._public_sources(all_sources)})
            yield self._sse("tools_done", {"tools": tool_calls_made, "iterations": iterations})
            for chunk in self.llm.iter_text_chunks(final_answer, chunk_size=12):
                yield self._sse("token", {"token": chunk, "kind": "response"})
            break

        if not final_answer and tool_calls_made:
            messages.append({"role": "user", "content": "以上工具已全部执行完毕。请用中文总结完成了哪些操作，以及最终结果。"})
            yield self._sse("sources", {"sources": self._public_sources(all_sources)})
            yield self._sse("tools_done", {"tools": tool_calls_made, "iterations": iterations})
            try:
                collect_buf = ""
                for token in self._call_llm_stream(messages[-8:], tools=False, model=model, provider=provider):
                    collect_buf += token
                    yield self._sse("token", {"token": token, "kind": "response"})
                final_answer = collect_buf
            except Exception:
                final_answer = f"Agent 已执行 {len(tool_calls_made)} 个操作。"
                for chunk in self.llm.iter_text_chunks(final_answer):
                    yield self._sse("token", {"token": chunk, "kind": "response"})

        yield self._sse("done", {"session_id": session_id, "iterations": iterations})
        self._save(session_id, question, final_answer, document_id, tool_calls_made, all_sources, started_at, library=library)

    # ── 并行工具执行 ─────────────────────────────────────

    def _execute_parallel(self, tool_calls: list, question: str, document_id: str | None,
                          tool_calls_made: list, all_sources: list,
                          stream_callback=None, top_k: int | None = None,
                          library: str = "enterprise", permission_mode: str = "read_only") -> list[tuple]:
        """并行执行所有工具调用，返回 (tool_call, result, is_error) 列表."""
        def _exec_one(tc):
            func_name = tc["function"]["name"]
            try:
                func_args = self._tool_args(tc)
            except json.JSONDecodeError:
                return tc, f"参数解析失败：{tc['function']['arguments']}", True

            if document_id and "document_id" not in func_args:
                func_args["document_id"] = document_id
            if func_name == "knowledge_search" and "top_k" not in func_args:
                func_args["top_k"] = top_k or settings.default_top_k
            func_args["library"] = library
            func_args["permission_mode"] = permission_mode  # 传递给宿主操作工具

            tool_fn = self.tools.get(func_name)
            if not tool_fn:
                return tc, f"未知工具: {func_name}", True

            for attempt in range(self.MAX_RETRIES + 1):
                try:
                    result = tool_fn(**func_args)
                    return tc, result, False
                except Exception as e:
                    if attempt < self.MAX_RETRIES:
                        time.sleep(0.5)
                        continue
                    return tc, f"工具执行失败（重试 {self.MAX_RETRIES} 次后）: {e}", True
            return tc, "未知错误", True

        results = []
        if len(tool_calls) > 1:
            with ThreadPoolExecutor(max_workers=min(len(tool_calls), 4)) as pool:
                futures = {pool.submit(_exec_one, tc): tc for tc in tool_calls}
                for future in as_completed(futures):
                    tc, result, is_error = future.result()
                    results.append((tc, result, is_error))
        else:
            tc, result, is_error = _exec_one(tool_calls[0])
            results.append((tc, result, is_error))

        # 确保按原始顺序
        ordered = []
        for tc in tool_calls:
            for r in results:
                if r[0] is tc:
                    ordered.append(r)
                    break
            else:
                ordered.append((tc, "未执行", True))

        for tc, result, is_error in ordered:
            func_name = tc["function"]["name"]
            tool_calls_made.append(func_name)
            if func_name == "knowledge_search" and not is_error:
                try:
                    func_args = self._tool_args(tc)
                    sources = self.rag.search(query=func_args.get("query", question),
                                              document_id=func_args.get("document_id", document_id),
                                              top_k=func_args.get("top_k", top_k or settings.default_top_k),
                                              library=library)
                    all_sources.extend(sources)
                except Exception:
                    pass

        return ordered

    # ── 辅助方法 ─────────────────────────────────────────

    def _tool_args(self, tool_call: dict) -> dict:
        arguments = tool_call.get("function", {}).get("arguments", {})
        if isinstance(arguments, dict):
            return dict(arguments)
        if not arguments:
            return {}
        return json.loads(arguments)

    def _build_llm_failure_fallback(
        self,
        question: str,
        document_id: str | None,
        top_k: int,
        library: str,
        exc: Exception,
        all_sources: list,
        tool_calls_made: list,
    ) -> str:
        if not settings.fallback_when_llm_unavailable:
            return f"Agent 调用失败：{exc}"
        try:
            sources = self.rag.search(query=question, document_id=document_id, top_k=top_k, library=library)
            all_sources.extend(sources)
            tool_calls_made.append("knowledge_search")
            fallback = self.rag.build_extractive_fallback(sources)
            return f"{fallback}\n\n提示：LLM 调用失败，已使用本地检索兜底。错误信息：{exc}"
        except Exception:
            return f"Agent 调用失败：{exc}"

    def _operation_answer(self, operation_request: dict) -> str:
        commands = "\n".join(f"- `{command}`" for command in operation_request.get("commands", []))
        return (
            "我已生成一个需要你批准的本地操作。点击下方“批准执行”后才会真正执行。\n\n"
            f"{operation_request.get('summary', '')}\n\n"
            f"将执行：\n{commands}"
        )

    def _public_sources(self, sources: list[dict]) -> list[dict]:
        seen = set()
        result = []
        for s in sources:
            cid = s.get("chunk_id", "")
            if cid in seen:
                continue
            seen.add(cid)
            result.append({"filename": s.get("filename", ""), "chunk_id": cid,
                           "similarity_score": s.get("similarity_score"),
                           "content_preview": s.get("content_preview", ""),
                           "document_id": s.get("document_id", ""), "page": s.get("page")})
        return result

    def _save(self, session_id, question, answer, document_id, tools, sources, started_at, library="enterprise"):
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        tool_str = ", ".join(tools) if tools else None
        self.memory.add_message(session_id=session_id, role="user", content=question, document_id=document_id, library=library)
        self.memory.add_message(session_id=session_id, role="assistant", content=answer, document_id=document_id, tool_name=tool_str, library=library)
        self.logger.log_query(question=question, session_id=session_id, hit_count=len(sources),
                              tool_names=tools, response_time_ms=elapsed_ms,
                              hit_knowledge_base=bool(sources), answer=answer)

    def _sse(self, event: str, data: dict) -> str:
        payload = json.dumps(data, ensure_ascii=False)
        # 转义换行符防止 SSE 注入，将 \n 替换为 \\n
        payload = payload.replace("\n", "\\n").replace("\r", "\\r")
        return f"event: {event}\ndata: {payload}\n\n"


_agent_service: ReActAgent | None = None
_agent_lock = threading.Lock()


def get_agent_service() -> ReActAgent:
    global _agent_service
    if _agent_service is None:
        with _agent_lock:
            if _agent_service is None:
                _agent_service = ReActAgent()
    return _agent_service
