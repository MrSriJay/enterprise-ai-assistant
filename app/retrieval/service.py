"""Index lifecycle and the knowledge-search tool used by the agents."""

from __future__ import annotations

import asyncio
import threading

from app.auth.rbac import allowed_levels
from app.config import get_settings
from app.logging_config import get_logger
from app.retrieval.corpus import corpus_fingerprint, load_corpus
from app.retrieval.embeddings import embed_query, embed_texts, embedding_name
from app.retrieval.index import LocalHybridIndex
from app.retrieval import pinecone_store

logger = get_logger(__name__)

_LOCK = threading.Lock()
_INDEX = LocalHybridIndex()
_REMOVED_LINES = 0


def ensure_index(force: bool = False) -> int:
    settings = get_settings()
    fingerprint = corpus_fingerprint(settings.docs_dir, embedding_name())
    with _LOCK:
        if not force and _INDEX.records and _INDEX.meta.get("fingerprint") == fingerprint:
            return len(_INDEX.records)
        if not force and _INDEX.load(settings.resolved_index_dir) and _INDEX.meta.get("fingerprint") == fingerprint:
            return len(_INDEX.records)
    return rebuild_index()


def rebuild_index() -> int:
    global _REMOVED_LINES
    settings = get_settings()
    records, removed = load_corpus(settings.docs_dir)
    vectors = embed_texts([record["text"] for record in records]) if records else embed_texts([""])[:0]
    fingerprint = corpus_fingerprint(settings.docs_dir, embedding_name())
    meta = {
        "fingerprint": fingerprint,
        "embedding": embedding_name(),
        "chunks": len(records),
        "untrusted_lines_removed": removed,
    }
    fresh = LocalHybridIndex()
    fresh.build(records, vectors, meta)
    fresh.save(settings.resolved_index_dir)
    pinecone_error = pinecone_store.upsert(records, vectors) if settings.pinecone_configured else None
    if pinecone_error:
        logger.warning("Continuing with the local index", extra={"fields": {"pinecone_error": pinecone_error}})
    with _LOCK:
        _INDEX.build(records, vectors, meta)
        _REMOVED_LINES = removed
    logger.info(
        "Knowledge index ready",
        extra={"fields": {"chunks": len(records), "removed_lines": removed, "embedding": meta["embedding"]}},
    )
    return len(records)


def index_status() -> dict:
    with _LOCK:
        meta = dict(_INDEX.meta)
        chunks = len(_INDEX.records)
    return {
        "chunks": chunks,
        "embedding": meta.get("embedding", embedding_name()),
        "untrusted_lines_removed": meta.get("untrusted_lines_removed", _REMOVED_LINES),
        "pinecone": pinecone_store.status(),
    }


async def search_knowledge(
    query: str,
    *,
    role: str,
    department: str | None = None,
    document_type: str | None = None,
    created_date_gte: str | None = None,
    doc_ids: list[str] | None = None,
    top_k: int | None = None,
) -> dict:
    """Hybrid search with a timeout. Failures become an empty hit list."""

    settings = get_settings()
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                _search_sync,
                query,
                role,
                department,
                document_type,
                created_date_gte,
                doc_ids,
                top_k or settings.retrieval_top_k,
            ),
            timeout=settings.retrieval_timeout_seconds,
        )
    except TimeoutError:
        logger.exception("Retrieval timed out")
        return {"hits": [], "degradation": ["retrieval timed out"]}
    except Exception as exc:
        logger.exception("Retrieval failed")
        return {"hits": [], "degradation": [f"vector store unavailable ({type(exc).__name__})"]}


def catalog_for(role: str) -> list[dict]:
    with _LOCK:
        return _INDEX.catalog(allowed_levels(role))


def documents_for(role: str, doc_ids: list[str]) -> list[dict]:
    with _LOCK:
        return _INDEX.documents(doc_ids, allowed_levels(role))


def _search_sync(
    query: str,
    role: str,
    department: str | None,
    document_type: str | None,
    created_date_gte: str | None,
    doc_ids: list[str] | None,
    top_k: int,
) -> dict:
    degradation: list[str] = []
    vector = embed_query(query)
    levels = allowed_levels(role)
    with _LOCK:
        local_hits = _INDEX.query(
            query,
            vector,
            access_levels=levels,
            department=department,
            document_type=document_type,
            created_date_gte=created_date_gte,
            doc_ids=set(doc_ids) if doc_ids is not None else None,
            top_k=top_k,
        )
        by_chunk = {record["chunk_id"]: record for record in _INDEX.records}
    if get_settings().pinecone_configured:
        pine_hits, error = pinecone_store.query(
            vector,
            access_levels=levels,
            department=department,
            document_type=document_type,
            created_date_gte=created_date_gte,
            top_k=top_k,
        )
        if error:
            degradation.append(f"pinecone unavailable ({error})")
        else:
            local_hits = _merge_pinecone(local_hits, pine_hits, by_chunk, query, top_k)
    return {"hits": local_hits, "degradation": degradation}


def _merge_pinecone(
    local_hits: list[dict],
    pine_hits: list[dict],
    by_chunk: dict[str, dict],
    query: str,
    top_k: int,
) -> list[dict]:
    from app.retrieval.rerank import rerank

    merged = {hit["chunk_id"]: dict(hit) for hit in local_hits}
    for hit in pine_hits:
        chunk_id = hit.get("chunk_id")
        record = by_chunk.get(chunk_id)
        if record is None:
            continue
        current = merged.get(chunk_id)
        dense = max(float(hit.get("dense_score") or 0), float(current.get("dense_score") if current else 0))
        if current is None:
            current = {**record, "sparse_score": 0.0, "dense_score": dense}
        else:
            current["dense_score"] = dense
        alpha = get_settings().hybrid_alpha
        current["hybrid_score"] = round(alpha * dense + (1 - alpha) * float(current.get("sparse_score") or 0), 4)
        merged[chunk_id] = current
    return rerank(query, list(merged.values()), top_k)
