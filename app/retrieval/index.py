"""Local hybrid index: cosine dense search plus BM25, then a rerank.

Namespaces are the document department. Metadata filters (access level, type,
date) are applied before scoring so a role never receives a vector from a
document it cannot read.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from app.config import get_settings
from app.retrieval.bm25 import BM25Index
from app.retrieval.rerank import rerank


class LocalHybridIndex:
    def __init__(self) -> None:
        self.records: list[dict] = []
        self.vectors: np.ndarray = np.zeros((0, 0), dtype=np.float32)
        self.bm25 = BM25Index([])
        self.meta: dict = {}

    def build(self, records: list[dict], vectors: np.ndarray, meta: dict) -> None:
        self.records = records
        self.vectors = vectors.astype(np.float32)
        self.bm25 = BM25Index([record["text"] for record in records])
        self.meta = meta

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        payload = {"meta": self.meta, "records": self.records}
        (directory / "records.json").write_text(json.dumps(payload), encoding="utf-8")
        np.save(directory / "vectors.npy", self.vectors)

    def load(self, directory: Path) -> bool:
        records_path = directory / "records.json"
        vectors_path = directory / "vectors.npy"
        if not records_path.exists() or not vectors_path.exists():
            return False
        payload = json.loads(records_path.read_text(encoding="utf-8"))
        vectors = np.load(vectors_path)
        self.build(payload["records"], vectors, payload.get("meta") or {})
        return True

    def query(
        self,
        query: str,
        query_vector: np.ndarray,
        *,
        access_levels: list[str],
        department: str | None = None,
        document_type: str | None = None,
        created_date_gte: str | None = None,
        doc_ids: set[str] | None = None,
        top_k: int = 6,
    ) -> list[dict]:
        candidates = [
            index
            for index, record in enumerate(self.records)
            if _matches(
                record,
                access_levels=access_levels,
                department=department,
                document_type=document_type,
                created_date_gte=created_date_gte,
                doc_ids=doc_ids,
            )
        ]
        if not candidates:
            return []
        dense_scores = _dense_scores(self.vectors, query_vector, candidates)
        hits: list[dict] = []
        lowered_query = query.lower()
        for position, index in enumerate(candidates):
            record = self.records[index]
            sparse = self.bm25.saturate(self.bm25.score(query, index))
            dense = max(0.0, float(dense_scores[position]))
            alpha = get_settings().hybrid_alpha
            hybrid = alpha * dense + (1.0 - alpha) * sparse
            if record["doc_id"].lower() in lowered_query:
                hybrid += 1.0
            if hybrid < 0.18 and record["doc_id"].lower() not in lowered_query:
                continue
            hits.append(
                {
                    **record,
                    "dense_score": round(dense, 4),
                    "sparse_score": round(sparse, 4),
                    "hybrid_score": round(hybrid, 4),
                }
            )
        return rerank(query, hits, top_k)

    def catalog(self, access_levels: list[str]) -> list[dict]:
        seen: set[str] = set()
        rows: list[dict] = []
        allowed = set(access_levels)
        for record in self.records:
            if record["doc_id"] in seen or record["access_level"] not in allowed:
                continue
            seen.add(record["doc_id"])
            preview = " ".join(record["text"].split())[:180]
            rows.append(
                {
                    "doc_id": record["doc_id"],
                    "title": record["title"],
                    "department": record["department"],
                    "document_type": record["document_type"],
                    "access_level": record["access_level"],
                    "created_date": record["created_date"],
                    "root_cause": record.get("root_cause") or "",
                    "preview": preview,
                }
            )
        return rows

    def documents(self, doc_ids: list[str], access_levels: list[str]) -> list[dict]:
        allowed = set(access_levels)
        wanted = set(doc_ids)
        grouped: dict[str, dict] = {}
        for record in self.records:
            if record["doc_id"] not in wanted or record["access_level"] not in allowed:
                continue
            current = grouped.get(record["doc_id"])
            if current is None:
                grouped[record["doc_id"]] = dict(record)
            else:
                current["text"] = current["text"] + "\n" + record["text"]
        return [grouped[doc_id] for doc_id in doc_ids if doc_id in grouped]


def _matches(
    record: dict,
    *,
    access_levels: list[str],
    department: str | None,
    document_type: str | None,
    created_date_gte: str | None,
    doc_ids: set[str] | None,
) -> bool:
    if record["access_level"] not in access_levels:
        return False
    if department and record["department"] != department:
        return False
    if document_type and record["document_type"] != document_type:
        return False
    if created_date_gte and record["created_date"] < created_date_gte:
        return False
    if doc_ids is not None and record["doc_id"] not in doc_ids:
        return False
    return True


def _dense_scores(vectors: np.ndarray, query_vector: np.ndarray, candidates: list[int]) -> np.ndarray:
    if vectors.size == 0 or query_vector.size == 0:
        return np.zeros(len(candidates), dtype=np.float32)
    matrix = vectors[candidates]
    query_norm = float(np.linalg.norm(query_vector))
    row_norms = np.linalg.norm(matrix, axis=1)
    denominators = np.maximum(row_norms * query_norm, 1e-9)
    return (matrix @ query_vector) / denominators
