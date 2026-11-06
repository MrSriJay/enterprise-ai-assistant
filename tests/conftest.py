"""Test environment. External providers stay disabled."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
os.environ["DATA_DIR"] = str(ROOT / "data")
os.environ["INDEX_DIR"] = str(ROOT / "data" / "index-test")
os.environ["MEMORY_DB"] = str(ROOT / "data" / "memory-test.sqlite")
os.environ["LLM_ENABLED"] = "false"
os.environ["OPENAI_API_KEY"] = ""
os.environ["PINECONE_API_KEY"] = ""
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["APP_TODAY"] = "2026-11-06"
os.environ["LOCAL_TRACE"] = "false"
os.environ["RATE_LIMIT_CAPACITY"] = "1000"
os.environ["RATE_LIMIT_REFILL_PER_MINUTE"] = "1000"
os.environ["MCP_URL"] = "http://127.0.0.1:9/mcp"
os.environ["MCP_FALLBACK"] = "true"
os.environ["MCP_TIMEOUT_SECONDS"] = "0.4"
os.environ["SESSION_SECRET"] = "test-secret"


@pytest.fixture(scope="session", autouse=True)
def knowledge_index():
    db_path = Path(os.environ["MEMORY_DB"])
    if db_path.exists():
        db_path.unlink()
    from app.retrieval.service import ensure_index

    ensure_index(force=True)
    yield
