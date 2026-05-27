import pytest

from app.core import embeddings


def test_lexical_embedding_is_normalized_and_deterministic():
    embedder = embeddings.LexicalEmbeddingFunction(dim=32)

    first = embedder.embed_query("MFNet LoRA shallow stages 指标")
    second = embedder.embed_query("MFNet LoRA shallow stages 指标")

    assert first == second
    assert len(first) == 32
    assert pytest.approx(sum(value * value for value in first), rel=1e-6) == 1.0


def test_embedding_provider_failure_raises_by_default(monkeypatch):
    def fail_init(self, model_name):
        raise RuntimeError("download failed")

    monkeypatch.setattr(embeddings.settings, "embedding_provider", "sentence_transformers")
    monkeypatch.setattr(embeddings.settings, "embedding_fallback", "error")
    monkeypatch.setattr(embeddings.SentenceTransformerEmbeddingFunction, "__init__", fail_init)

    with pytest.raises(RuntimeError, match="Embedding 初始化失败"):
        embeddings.build_embedding_function()


def test_embedding_provider_can_use_explicit_lexical_fallback(monkeypatch):
    def fail_init(self, model_name):
        raise RuntimeError("download failed")

    monkeypatch.setattr(embeddings.settings, "embedding_provider", "sentence_transformers")
    monkeypatch.setattr(embeddings.settings, "embedding_fallback", "lexical")
    monkeypatch.setattr(embeddings.SentenceTransformerEmbeddingFunction, "__init__", fail_init)

    embedder = embeddings.build_embedding_function()

    assert isinstance(embedder, embeddings.LexicalEmbeddingFunction)
