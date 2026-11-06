"""Optional Pinecone dense leg.

The local index stays the system of record for text and BM25. Pinecone, when
configured, adds a namespaced dense query with the same metadata filters.
A Pinecone miss degrades to the local hybrid result instead of failing the chat.
"""

from __future__ import annotations

from app.config import get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)

_client = None
_init_error: str | None = None
_checked = False


def status() -> dict:
    _ensure_client()
    settings = get_settings()
    return {
        "configured": settings.pinecone_configured,
        "ready": _client is not None,
        "index": settings.pinecone_index if settings.pinecone_configured else "",
        "error": _init_error,
    }


def upsert(records: list[dict], vectors) -> str | None:
    index = _ensure_client()
    if index is None:
        return _init_error
    try:
        by_namespace: dict[str, list[dict]] = {}
        for record, vector in zip(records, vectors):
            by_namespace.setdefault(record["namespace"], []).append(
                {
                    "id": record["chunk_id"],
                    "values": [float(value) for value in vector],
                    "metadata": {
                        "doc_id": record["doc_id"],
                        "chunk_id": record["chunk_id"],
                        "title": record["title"],
                        "department": record["department"],
                        "document_type": record["document_type"],
                        "access_level": record["access_level"],
                        "created_date": record["created_date"],
                        "text": record["text"][:8000],
                    },
                }
            )
        for namespace, rows in by_namespace.items():
            for start in range(0, len(rows), 100):
                index.upsert(vectors=rows[start : start + 100], namespace=namespace)
        return None
    except Exception as exc:
        logger.exception("Pinecone upsert failed")
        return type(exc).__name__


def query(
    query_vector,
    *,
    access_levels: list[str],
    department: str | None,
    document_type: str | None,
    created_date_gte: str | None,
    top_k: int,
) -> tuple[list[dict], str | None]:
    index = _ensure_client()
    if index is None:
        return [], _init_error if get_settings().pinecone_configured else None
    metadata_filter: dict = {"access_level": {"$in": list(access_levels)}}
    if document_type:
        metadata_filter["document_type"] = {"$eq": document_type}
    if created_date_gte:
        metadata_filter["created_date"] = {"$gte": created_date_gte}
    namespaces = [department] if department else _namespaces()
    hits: list[dict] = []
    try:
        for namespace in namespaces:
            response = index.query(
                vector=[float(value) for value in query_vector],
                top_k=top_k,
                namespace=namespace,
                filter=metadata_filter,
                include_metadata=True,
            )
            matches = response.get("matches", []) if isinstance(response, dict) else response.matches
            for match in matches:
                metadata = match["metadata"] if isinstance(match, dict) else match.metadata
                score = match["score"] if isinstance(match, dict) else match.score
                hits.append(
                    {
                        "chunk_id": metadata.get("chunk_id"),
                        "doc_id": metadata.get("doc_id"),
                        "dense_score": float(score or 0),
                    }
                )
        return hits, None
    except Exception as exc:
        logger.exception("Pinecone query failed")
        return [], type(exc).__name__


def _namespaces() -> list[str]:
    return ["payments", "security", "retail", "platform", "people", "risk"]


def _ensure_client():
    global _client, _init_error, _checked
    if _checked:
        return _client
    _checked = True
    settings = get_settings()
    if not settings.pinecone_configured:
        return None
    try:
        from pinecone import Pinecone

        client = Pinecone(api_key=settings.pinecone_api_key)
        _client = client.Index(settings.pinecone_index)
        return _client
    except Exception as exc:
        _init_error = f"{type(exc).__name__}: {exc}"
        logger.warning("Pinecone is configured but unavailable", extra={"fields": {"error": _init_error}})
        return None
