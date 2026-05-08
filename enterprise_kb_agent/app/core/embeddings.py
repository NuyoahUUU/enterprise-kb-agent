import hashlib
import logging
import math
import re
from collections import Counter
from typing import Iterable

import requests

from app.core.config import settings


logger = logging.getLogger(__name__)


class LexicalEmbeddingFunction:
    """Explicit lexical fallback for environments without semantic embedding models."""

    def __init__(self, dim: int = 384):
        self.dim = dim

    def __call__(self, input: Iterable[str]) -> list[list[float]]:
        return [self._embed(text) for text in input]

    def embed_documents(self, input: Iterable[str]) -> list[list[float]]:
        return self.__call__(input)

    def embed_query(self, input: str | Iterable[str]) -> list[float] | list[list[float]]:
        if isinstance(input, str):
            return self._embed(input)
        return self.__call__(input)

    def name(self) -> str:
        return "lexical-fallback"

    def _embed(self, text: str) -> list[float]:
        features = self._features(text)
        vec = [0.0] * self.dim
        for feature, count in features.items():
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            idx = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if digest[4] % 2 else -1.0
            vec[idx] += sign * (1.0 + math.log(count))
        norm = math.sqrt(sum(value * value for value in vec)) or 1.0
        return [value / norm for value in vec]

    def _features(self, text: str) -> Counter:
        normalized = text.lower()
        words = re.findall(r"[a-z0-9_+\-/.]{2,}|[\u4e00-\u9fff]", normalized)
        features = Counter(words)

        cjk_chars = re.findall(r"[\u4e00-\u9fff]", normalized)
        features.update("".join(cjk_chars[idx : idx + 2]) for idx in range(max(len(cjk_chars) - 1, 0)))

        latin_words = re.findall(r"[a-z0-9_+\-/.]{4,}", normalized)
        for word in latin_words:
            features.update(word[idx : idx + 3] for idx in range(max(len(word) - 2, 0)))
        return features


class SentenceTransformerEmbeddingFunction:
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name)

    def __call__(self, input: Iterable[str]) -> list[list[float]]:
        embeddings = self.model.encode(list(input), normalize_embeddings=True)
        return embeddings.tolist()

    def embed_documents(self, input: Iterable[str]) -> list[list[float]]:
        return self.__call__(input)

    def embed_query(self, input: str | Iterable[str]) -> list[float] | list[list[float]]:
        if isinstance(input, str):
            return self.__call__([input])[0]
        return self.__call__(input)

    def name(self) -> str:
        return f"sentence-transformers-{settings.embedding_model_name}"


class OpenAIEmbeddingFunction:
    def __init__(self):
        if not settings.openai_api_key:
            raise ValueError("使用 OpenAI Embedding 时必须配置 OPENAI_API_KEY")
        self.api_key = settings.openai_api_key
        self.base_url = settings.openai_base_url.rstrip("/")
        self.model = settings.openai_embedding_model

    def __call__(self, input: Iterable[str]) -> list[list[float]]:
        response = requests.post(
            f"{self.base_url}/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"model": self.model, "input": list(input)},
            timeout=settings.llm_timeout,
        )
        response.raise_for_status()
        data = response.json()["data"]
        return [item["embedding"] for item in sorted(data, key=lambda item: item["index"])]

    def embed_documents(self, input: Iterable[str]) -> list[list[float]]:
        return self.__call__(input)

    def embed_query(self, input: str | Iterable[str]) -> list[float] | list[list[float]]:
        if isinstance(input, str):
            return self.__call__([input])[0]
        return self.__call__(input)

    def name(self) -> str:
        return f"openai-{settings.openai_embedding_model}"


def build_embedding_function():
    try:
        if settings.embedding_provider == "openai":
            return OpenAIEmbeddingFunction()
        return SentenceTransformerEmbeddingFunction(settings.embedding_model_name)
    except Exception as exc:
        if settings.embedding_fallback == "lexical":
            logger.warning("Embedding provider unavailable; using lexical fallback: %s", exc)
            return LexicalEmbeddingFunction()
        raise RuntimeError(
            "Embedding 初始化失败。请安装/下载 SentenceTransformer 模型，配置 OpenAI Embedding，"
            "或显式设置 EMBEDDING_FALLBACK=lexical 使用词法检索兜底。"
        ) from exc
