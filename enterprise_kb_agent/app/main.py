from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import chat, operations, stats, upload
from app.config import settings
from app.core.vectorstore import get_vectorstore_service
from app.database import init_db
from app.routers import agent_router, document_router
from app.services.document_service import DocumentService
from app.utils.response import error_response, success_response


STATIC_DIR = Path(__file__).resolve().parent / "static"
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_directories()
    init_db()
    try:
        get_vectorstore_service()._repair_corrupt_storage_before_chroma_import()
    except Exception as exc:
        logger.warning("ChromaDB repair check skipped: %s", exc)
    try:
        result = DocumentService().reindex_existing_documents(only_if_empty=True)
        if not result.get("skipped"):
            logger.info("Reindexed existing documents on startup: %s", result)
    except Exception as exc:
        logger.warning("Document reindex skipped during startup: %s", exc)
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="基于 FastAPI + LangChain + ChromaDB + Ollama 的企业知识库 Agent 平台",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router)
app.include_router(chat.router)
app.include_router(operations.router)
app.include_router(stats.router)

# Backward-compatible routers kept for older demos.
app.include_router(document_router.router)
app.include_router(agent_router.router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def web_client():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health", tags=["health"])
def health_check():
    return success_response({"status": "ok", "app": settings.app_name, "version": settings.app_version})


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response(message=str(exc.detail), code=exc.status_code),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content=error_response(message=str(exc.errors()), code=422),
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(
        status_code=400,
        content=error_response(message=str(exc), code=400),
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content=error_response(message="服务器内部错误，请稍后重试", code=500),
    )
