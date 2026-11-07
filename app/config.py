"""Runtime configuration.

Secrets come from the environment or a local ``.env`` file. The defaults are
deliberately offline: the graph, retrieval, and guardrails run without an API
key so the architecture can be reviewed on its own.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Enterprise AI Assistant"
    company_name: str = "Enterprise AI Assistant"
    data_dir: Path = Path("data")
    index_dir: Path | None = None
    memory_db: Path | None = None

    llm_enabled: bool = False
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    chat_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    use_openai_embeddings: bool = False
    embedding_dim: int = 256

    pinecone_api_key: str = ""
    pinecone_index: str = "harborline-assistant"

    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "harborline-assistant"
    local_trace: bool = True

    mcp_url: str = "http://127.0.0.1:8100/mcp"
    mcp_fallback: bool = True
    mcp_timeout_seconds: float = 5.0

    rate_limit_capacity: float = 10
    rate_limit_refill_per_minute: float = 6
    retrieval_timeout_seconds: float = 12
    tool_timeout_seconds: float = 8
    llm_timeout_seconds: float = 40
    max_message_chars: int = 4000

    hybrid_alpha: float = 0.35
    retrieval_top_k: int = 6
    rlm_batch_size: int = 3
    rlm_max_depth: int = 4
    rlm_char_limit: int = 900

    session_secret: str = "change-me-before-any-shared-demo"
    cors_origins: str = "http://localhost:8501,http://127.0.0.1:8501"
    app_today: str = ""

    @property
    def docs_dir(self) -> Path:
        return self.data_dir / "documents"

    @property
    def resolved_index_dir(self) -> Path:
        return self.index_dir or (self.data_dir / "index")

    @property
    def resolved_memory_db(self) -> Path:
        return self.memory_db or (self.data_dir / "memory.sqlite")

    @property
    def trace_path(self) -> Path:
        return self.data_dir / "traces.jsonl"

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def llm_ready(self) -> bool:
        return bool(self.llm_enabled and self.openai_api_key.strip())

    @property
    def openai_embeddings_ready(self) -> bool:
        return bool(self.llm_ready and self.use_openai_embeddings)

    @property
    def pinecone_configured(self) -> bool:
        return bool(self.pinecone_api_key.strip())

    @property
    def langsmith_ready(self) -> bool:
        return bool(self.langsmith_tracing and self.langsmith_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
