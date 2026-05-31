import logging
import shutil
import sqlite3
import threading as _threading
from datetime import datetime
from typing import Optional

from app.core.config import settings
from app.core.embeddings import build_embedding_function


logger = logging.getLogger(__name__)
_collection_lock = _threading.Lock()

LIBRARIES = {
    "enterprise": "kb_enterprise",
    "research": "kb_research",
}


class VectorStoreService:
    """Multi-collection ChromaDB with library switching."""

    def __init__(self):
        import chromadb
        self.client = chromadb.PersistentClient(path=str(settings.chroma_db_dir))
        self._embedding_fn = build_embedding_function()
        self._collections = {}

    def _get_collection(self, library: str = "enterprise"):
        name = LIBRARIES.get(library, LIBRARIES["enterprise"])
        if name not in self._collections:
            with _collection_lock:
                if name not in self._collections:
                    self._collections[name] = self.client.get_or_create_collection(
                        name=name,
                        embedding_function=self._embedding_fn,
                        metadata={"hnsw:space": "cosine"},
                    )
        return self._collections[name]

    def add_documents(self, document_id: str, filename: str, chunks: list, library: str = "enterprise") -> None:
        if not chunks:
            return
        col = self._get_collection(library)
        ids, documents, metadatas = [], [], []
        for idx, chunk in enumerate(chunks):
            content = str(chunk.get("content", "") if isinstance(chunk, dict) else chunk).strip()
            if not content:
                continue
            chunk_id = f"{document_id}_{idx}"
            metadata = {"document_id": document_id, "filename": filename, "chunk_id": chunk_id,
                        "chunk_index": idx, "char_count": len(content), "library": library}
            if isinstance(chunk, dict) and chunk.get("page"):
                metadata["page"] = int(chunk["page"])
            ids.append(chunk_id)
            documents.append(content)
            metadatas.append(metadata)
        if ids:
            col.upsert(ids=ids, documents=documents, metadatas=metadatas)

    def search(self, query: str, document_id: Optional[str] = None, top_k: Optional[int] = None,
               library: str = "enterprise") -> list[dict]:
        col = self._get_collection(library)
        if col.count() == 0:
            return []
        where = {"document_id": document_id} if document_id else None
        result = col.query(query_texts=[query], n_results=top_k or settings.default_top_k,
                           where=where, include=["documents", "metadatas", "distances"])
        sources = []
        for chunk_id, content, metadata, distance in zip(
            result.get("ids", [[]])[0], result.get("documents", [[]])[0],
            result.get("metadatas", [[]])[0], result.get("distances", [[]])[0],
        ):
            sources.append(self._source_from_hit(chunk_id, content, metadata, distance))
        return sources

    def get_document_chunks(self, document_id: str, library: str = "enterprise") -> list[dict]:
        col = self._get_collection(library)
        result = col.get(where={"document_id": document_id}, include=["documents", "metadatas"])
        chunks = []
        for chunk_id, content, metadata in zip(result.get("ids", []), result.get("documents", []),
                                                result.get("metadatas", [])):
            chunks.append(self._source_from_hit(chunk_id, content, metadata, distance=None))
        return sorted(chunks, key=lambda item: item.get("chunk_index", 0))

    def delete_document(self, document_id: str, library: str = "enterprise") -> None:
        col = self._get_collection(library)
        try:
            col.delete(where={"document_id": document_id})
        except Exception:
            logger.warning("Failed to delete vectors for document_id=%s in %s", document_id, library, exc_info=True)

    def count(self, library: str = "enterprise") -> int:
        return self._get_collection(library).count()

    def _source_from_hit(self, chunk_id: str, content: str, metadata: dict, distance: float | None) -> dict:
        score = None if distance is None else round(max(0.0, min(1.0, 1 - float(distance))), 4)
        return {
            "document_id": metadata.get("document_id", ""),
            "filename": metadata.get("filename", ""),
            "chunk_id": metadata.get("chunk_id", chunk_id),
            "chunk_index": int(metadata.get("chunk_index", 0)),
            "page": metadata.get("page"),
            "similarity_score": score,
            "content_preview": " ".join(content.split())[:220],
            "content": content,
            "library": metadata.get("library", ""),
        }

    def _repair_corrupt_storage_before_chroma_import(self) -> None:
        sqlite_path = settings.chroma_db_dir / "chroma.sqlite3"
        if not sqlite_path.exists():
            return
        try:
            with sqlite3.connect(sqlite_path) as connection:
                result = connection.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.DatabaseError as exc:
            self._archive_corrupt_storage(exc)
            return
        if not result or result[0] != "ok":
            self._archive_corrupt_storage(RuntimeError(f"Chroma integrity check failed: {result}"))

    def _archive_corrupt_storage(self, exc: Exception) -> None:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        backup_dir = settings.chroma_db_dir.with_name(f"{settings.chroma_db_dir.name}.corrupt-{timestamp}")
        logger.warning("Chroma storage corrupt; moving %s to %s: %s", settings.chroma_db_dir, backup_dir, exc)
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        shutil.move(str(settings.chroma_db_dir), str(backup_dir))
        settings.chroma_db_dir.mkdir(parents=True, exist_ok=True)
        (settings.chroma_db_dir / ".gitkeep").touch(exist_ok=True)


_vectorstore_service: VectorStoreService | None = None
_vs_lock = _threading.Lock()


def get_vectorstore_service() -> VectorStoreService:
    global _vectorstore_service
    if _vectorstore_service is None:
        with _vs_lock:
            if _vectorstore_service is None:
                _vectorstore_service = VectorStoreService()
    return _vectorstore_service
