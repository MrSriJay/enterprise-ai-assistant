"""FastAPI entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.config import get_settings
from app.errors import AppError
from app.logging_config import configure_logging, get_logger
from app.memory.store import init_db
from app.observability import configure_tracing
from app.retrieval.service import ensure_index, index_status

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging()
    configure_tracing()
    init_db()
    chunks = ensure_index()
    logger.info(
        "Assistant started",
        extra={
            "fields": {
                "chunks": chunks,
                "llm": settings.llm_ready,
                "pinecone": settings.pinecone_configured,
                "langsmith": settings.langsmith_ready,
            }
        },
    )
    if settings.session_secret == "change-me-before-any-shared-demo":
        logger.warning("SESSION_SECRET is still the demo default.")
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-RateLimit-Remaining", "X-Session-Id"],
    )
    app.include_router(router)

    @app.get("/api/health")
    async def health() -> dict:
        current = get_settings()
        status = index_status()
        return {
            "status": "ok",
            "company": current.company_name,
            "llm": current.llm_ready,
            "chat_model": current.chat_model if current.llm_ready else "grounded-extractive",
            "embeddings": status["embedding"],
            "chunks": status["chunks"],
            "untrusted_lines_removed": status["untrusted_lines_removed"],
            "pinecone": status["pinecone"],
            "langsmith": current.langsmith_ready,
            "langsmith_project": current.langsmith_project if current.langsmith_ready else "",
            "mcp_url": current.mcp_url,
        }

    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.as_dict())

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        message = "Request failed validation."
        if exc.errors():
            message = exc.errors()[0].get("msg", message)
        return JSONResponse(status_code=422, content={"error": "invalid_request", "message": message})

    return app


app = create_app()
