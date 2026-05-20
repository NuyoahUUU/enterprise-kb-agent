import json
import os
import threading as _threading
from collections import Counter
from datetime import datetime
from threading import RLock
from typing import Any

from app.core.config import settings


# 日志文件最大 10MB，保留最近 5 个轮转文件
MAX_LOG_SIZE_BYTES = 10 * 1024 * 1024
MAX_LOG_BACKUPS = 5


class QueryLogger:
    """JSONL query logger used by /stats and interview demos."""

    def __init__(self):
        settings.ensure_directories()
        self.path = settings.query_log_path
        self._lock = RLock()

    def log_query(
        self,
        question: str,
        session_id: str,
        hit_count: int,
        tool_names: list[str],
        response_time_ms: float,
        hit_knowledge_base: bool,
        answer: str,
    ) -> None:
        record = {
            "timestamp": datetime.now().isoformat(),
            "session_id": session_id,
            "question": question,
            "hit_count": hit_count,
            "tool_names": tool_names,
            "response_time_ms": round(response_time_ms, 2),
            "hit_knowledge_base": hit_knowledge_base,
            "answer_chars": len(answer),
        }
        with self._lock:
            self._rotate_if_needed()
            with self.path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _rotate_if_needed(self) -> None:
        """当日志文件超过上限时自动轮转。"""
        if not self.path.exists():
            return
        try:
            size = self.path.stat().st_size
        except OSError:
            return
        if size < MAX_LOG_SIZE_BYTES:
            return

        # 轮转：删除最旧的备份，将现有备份依次后移
        oldest = self.path.with_suffix(f".{MAX_LOG_BACKUPS}.jsonl")
        if oldest.exists():
            oldest.unlink()

        for i in range(MAX_LOG_BACKUPS - 1, 0, -1):
            old = self.path.with_suffix(f".{i}.jsonl")
            new = self.path.with_suffix(f".{i + 1}.jsonl")
            if old.exists():
                old.rename(new)

        backup = self.path.with_suffix(".1.jsonl")
        self.path.rename(backup)
        # 新日志文件由后续写入自动创建

    def get_stats(self) -> dict[str, Any]:
        """聚合当前日志和所有轮转备份的统计数据。"""
        log_paths = [self.path] + [
            self.path.with_suffix(f".{i}.jsonl")
            for i in range(1, MAX_LOG_BACKUPS + 1)
        ]

        total = 0
        response_time_sum = 0.0
        hit_count = 0
        tools = Counter()

        for path in log_paths:
            if not path.exists():
                continue
            with path.open("r", encoding="utf-8") as file:
                for line in file:
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    total += 1
                    response_time_sum += float(record.get("response_time_ms") or 0)
                    if record.get("hit_knowledge_base"):
                        hit_count += 1
                    tools.update(record.get("tool_names") or [])

        most_called_tool = tools.most_common(1)[0][0] if tools else None
        average = round(response_time_sum / total, 2) if total else 0
        return {
            "total_questions": total,
            "average_response_time_ms": average,
            "knowledge_base_hit_count": hit_count,
            "most_called_tool": most_called_tool,
            "tool_call_counts": dict(tools),
        }


_query_logger: QueryLogger | None = None
_logger_lock = _threading.Lock()


def get_query_logger() -> QueryLogger:
    global _query_logger
    if _query_logger is None:
        with _logger_lock:
            if _query_logger is None:
                _query_logger = QueryLogger()
    return _query_logger

