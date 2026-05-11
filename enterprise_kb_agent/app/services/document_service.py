import json
import re
from datetime import datetime
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.config import settings
from app.services.rag_service import get_rag_service
from app.utils.text_splitter import split_text


class DocumentService:
    allowed_extensions = {".pdf", ".txt", ".md"}
    _max_upload_size = 50 * 1024 * 1024  # 50 MB

    async def upload_document(self, file: UploadFile, library: str = "enterprise", overwrite: bool = False) -> dict:
        filename = file.filename or "uploaded_document.txt"
        extension = Path(filename).suffix.lower()
        if extension not in self.allowed_extensions:
            raise ValueError("仅支持 PDF / TXT / MD 文件上传")

        content = await file.read()
        if not content:
            raise ValueError("上传文件为空")
        if len(content) > self._max_upload_size:
            raise ValueError(f"上传文件大小不能超过 {self._max_upload_size // (1024 * 1024)}MB")

        text = self._parse_file(content, extension)
        if not text.strip():
            raise ValueError("文档解析结果为空，请检查文件内容")

        if extension == ".pdf" and library == "research":
            title = self._extract_pdf_title(text)
            if title:
                filename = title + ".pdf"

        existing = [doc for doc in self.list_documents(library) if doc.get("filename") == filename]
        if existing and not overwrite:
            raise ValueError(f"「{library}」库中已存在同名文档「{filename}」")
        if existing and overwrite:
            for doc in existing:
                self.delete_document(doc["document_id"], library)

        document_id = uuid4().hex
        safe_name = self._safe_filename(filename)
        raw_dir = settings.upload_dir / library
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_path = raw_dir / f"{document_id}_{safe_name}"
        raw_path.write_bytes(content)

        chunks = self._build_chunk_records(text)
        meta = {
            "document_id": document_id, "filename": filename, "raw_path": str(raw_path),
            "chunk_count": len(chunks), "char_count": len(text),
            "created_at": datetime.now().isoformat(), "library": library,
        }
        meta_path = raw_dir / f"{document_id}.json"
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        get_rag_service().add_document(document_id=document_id, filename=filename, chunks=chunks, library=library)
        return {"document_id": document_id, "filename": filename, "chunk_count": len(chunks), "char_count": len(text)}

    def get_document_text(self, document_id: str, library: str = "enterprise") -> str:
        meta = self.get_document_metadata(document_id, library)
        raw_path = Path(meta.get("raw_path", ""))
        if raw_path.exists():
            text = self._parse_file(raw_path.read_bytes(), raw_path.suffix.lower())
            if text.strip():
                return text
        chunks = get_rag_service().get_document_chunks(document_id, library)
        if chunks:
            return "\n\n".join(chunk["content"] for chunk in chunks)
        raise ValueError(f"未找到 document_id={document_id} 的文档")

    def get_document_metadata(self, document_id: str, library: str = "enterprise") -> dict:
        meta_path = settings.upload_dir / library / f"{document_id}.json"
        if not meta_path.exists():
            raise ValueError(f"未找到 document_id={document_id} 的元数据")
        return json.loads(meta_path.read_text(encoding="utf-8"))

    def list_documents(self, library: str = "enterprise") -> list[dict]:
        documents = []
        lib_dir = settings.upload_dir / library
        if not lib_dir.exists():
            return documents
        for path in lib_dir.glob("*.json"):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
                if doc.get("library") == library or "library" not in doc:
                    documents.append(doc)
            except Exception:
                continue
        return sorted(documents, key=lambda item: item.get("created_at", ""), reverse=True)

    def delete_document(self, document_id: str, library: str = "enterprise") -> dict:
        meta = self.get_document_metadata(document_id, library)
        filename = meta.get("filename", "unknown")
        raw_path = Path(meta.get("raw_path", ""))
        if raw_path.exists():
            raw_path.unlink()
        meta_path = settings.upload_dir / library / f"{document_id}.json"
        if meta_path.exists():
            meta_path.unlink()
        try:
            get_rag_service().delete_document(document_id, library)
        except Exception:
            pass
        return {"document_id": document_id, "filename": filename, "deleted": True, "library": library}

    def reindex_existing_documents(self, only_if_empty: bool = True, library: str = "enterprise") -> dict:
        documents = self.list_documents(library)
        if not documents:
            return {"document_count": 0, "chunk_count": 0, "skipped": True}
        rag_service = get_rag_service()
        if only_if_empty and rag_service.vectorstore.count(library) > 0:
            return {"document_count": len(documents), "chunk_count": 0, "skipped": True}
        indexed_docs, indexed_chunks = 0, 0
        for meta in documents:
            document_id = meta.get("document_id")
            filename = meta.get("filename", "document")
            raw_path = Path(meta.get("raw_path", ""))
            if not document_id or not raw_path.exists():
                continue
            text = self._parse_file(raw_path.read_bytes(), raw_path.suffix.lower())
            chunks = self._build_chunk_records(text)
            if not chunks:
                continue
            rag_service.add_document(document_id=document_id, filename=filename, chunks=chunks, library=library)
            indexed_docs += 1
            indexed_chunks += len(chunks)
        return {"document_count": indexed_docs, "chunk_count": indexed_chunks, "skipped": False}

    def _parse_file(self, content: bytes, extension: str) -> str:
        if extension in (".txt", ".md"):
            for enc in ("utf-8", "utf-8-sig", "gbk", "latin-1"):
                try:
                    return content.decode(enc)
                except UnicodeDecodeError:
                    continue
            return content.decode("utf-8", errors="ignore")
        if extension == ".pdf":
            try:
                from pypdf import PdfReader
            except ImportError:
                raise ValueError("请先安装 pypdf 以支持 PDF 解析")
            reader = PdfReader(BytesIO(content))
            pages = []
            for idx, page in enumerate(reader.pages, start=1):
                page_text = page.extract_text() or ""
                pages.append(f"\n\n--- Page {idx} ---\n{page_text}")
            return "\n".join(pages)
        raise ValueError("不支持的文件类型")

    def _build_chunk_records(self, text: str) -> list[dict]:
        page_sections = self._split_pdf_page_sections(text)
        if not page_sections:
            return [{"content": chunk} for chunk in split_text(text)]
        chunks = []
        for page, page_text in page_sections:
            for chunk in split_text(page_text):
                chunks.append({"content": chunk, "page": page})
        return chunks

    def _split_pdf_page_sections(self, text: str) -> list[tuple[int, str]]:
        matches = list(re.finditer(r"\n*--- Page (?P<page>\d+) ---\n", text))
        if not matches:
            return []
        sections = []
        for idx, match in enumerate(matches):
            page = int(match.group("page"))
            start = match.end()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            page_text = text[start:end].strip()
            if page_text:
                sections.append((page, page_text))
        return sections

    def _extract_pdf_title(self, text: str) -> str | None:
        """从论文 PDF 的前几行提取标题."""
        lines = [l.strip() for l in text.split("\n")[:30] if l.strip()]
        # 跳过明显的元数据行
        skip_patterns = [
            r"^arXiv:", r"^DOI:", r"^https?://", r"^©", r"^Copyright",
            r"^\d+$", r"^[A-Z][a-z]+ \d+, \d{4}$", r"^Page \d+",
            r"^\[Submitted", r"^Preprint", r"^\d{1,2} (January|February|March|April|May|June|July|August|September|October|November|December) \d{4}$",
        ]
        candidates = []
        for line in lines:
            if any(re.match(p, line, re.IGNORECASE) for p in skip_patterns):
                continue
            # 标题特征：足够长、包含有意义的词
            if 20 <= len(line) <= 200 and re.search(r"[A-Za-z]{3,}", line):
                candidates.append(line)

        if candidates:
            # 优先选最长的（论文标题通常是最长的行之一）
            candidates.sort(key=len, reverse=True)
            title = candidates[0]
            # 清理
            title = re.sub(r"\s+", " ", title)
            title = re.sub(r'[\\/:*?"<>|]', "", title)[:120]
            return title.strip()
        return None

    def _safe_filename(self, filename: str) -> str:
        name = Path(filename).name
        return re.sub(r"[^A-Za-z0-9_.\-一-鿿]", "_", name)
