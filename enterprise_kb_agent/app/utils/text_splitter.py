from typing import List

from app.config import settings


def split_text(text: str, chunk_size: int | None = None, chunk_overlap: int | None = None) -> List[str]:
    """Split long research text into overlapping chunks."""

    clean_text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if not clean_text:
        return []

    size = chunk_size or settings.chunk_size
    overlap = chunk_overlap or settings.chunk_overlap

    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=size,
            chunk_overlap=overlap,
            separators=["\n\n", "\n", "。", "！", "？", ". ", "; ", ", ", " ", ""],
        )
        return [chunk.strip() for chunk in splitter.split_text(clean_text) if chunk.strip()]
    except Exception:
        chunks: list[str] = []
        start = 0
        while start < len(clean_text):
            end = start + size
            chunks.append(clean_text[start:end].strip())
            next_start = end - overlap
            start = next_start if next_start > start else end
        return [chunk for chunk in chunks if chunk]
