"""Load markdown documents, strip untrusted lines, and chunk them.

Each chunk keeps the parent document's metadata so Pinecone filters and the
local index apply the same access rules.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.security.injection import sanitize_untrusted

CHUNK_TARGET = 1400


def load_corpus(docs_dir: Path) -> tuple[list[dict], int]:
    records: list[dict] = []
    removed = 0
    paths = sorted(path for path in docs_dir.glob("*.md") if path.is_file())
    for path in paths:
        meta, body = _parse(path)
        clean, stripped = sanitize_untrusted(body)
        removed += stripped
        for index, chunk in enumerate(_chunk(clean)):
            text = f"{meta['title']}\n{chunk}".strip()
            records.append(
                {
                    "chunk_id": f"{meta['id']}#{index}",
                    "doc_id": meta["id"],
                    "title": meta["title"],
                    "department": meta["department"],
                    "document_type": meta["document_type"],
                    "access_level": meta["access_level"],
                    "created_date": meta["created_date"],
                    "root_cause": meta.get("root_cause", ""),
                    "namespace": meta["department"],
                    "source": path.name,
                    "text": text,
                }
            )
    return records, removed


def corpus_fingerprint(docs_dir: Path, embedding_name: str) -> str:
    digest = hashlib.sha256()
    digest.update(embedding_name.encode("utf-8"))
    for path in sorted(docs_dir.glob("*.md")):
        stat = path.stat()
        digest.update(path.name.encode("utf-8"))
        digest.update(str(stat.st_mtime_ns).encode("utf-8"))
        digest.update(str(stat.st_size).encode("utf-8"))
    return digest.hexdigest()[:20]


def _parse(path: Path) -> tuple[dict[str, str], str]:
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---\n"):
        raise ValueError(f"{path.name} is missing front matter")
    _, front_matter, body = raw.split("---", 2)
    meta: dict[str, str] = {}
    for line in front_matter.strip().splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip()
    required = ["id", "title", "department", "document_type", "access_level", "created_date"]
    missing = [key for key in required if not meta.get(key)]
    if missing:
        raise ValueError(f"{path.name} missing {', '.join(missing)}")
    return meta, body.strip()


def _chunk(text: str) -> list[str]:
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    if not paragraphs:
        return [text.strip() or "Empty document."]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if current and len(candidate) > CHUNK_TARGET:
            chunks.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks
