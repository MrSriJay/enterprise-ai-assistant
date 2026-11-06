"""Hybrid retrieval and access filters."""

from __future__ import annotations

import pytest

from app.retrieval.service import documents_for, search_knowledge


@pytest.mark.asyncio
async def test_hybrid_search_finds_the_rotation_runbook():
    result = await search_knowledge(
        "What does the certificate rotation runbook say about rollback?",
        role="viewer",
    )
    ids = [hit["doc_id"] for hit in result["hits"]]
    assert "rb-cert-rotation" in ids
    assert "sec-key-ceremony" not in ids


@pytest.mark.asyncio
async def test_roles_cannot_read_above_their_clearance():
    viewer = await search_knowledge("BONUS-POOL-CONFIDENTIAL-442 compensation", role="viewer")
    analyst = await search_knowledge("BONUS-POOL-CONFIDENTIAL-442 compensation", role="analyst")
    admin = await search_knowledge("CANARY-RESTRICTED-KEY-7741 ceremony", role="administrator")
    analyst_restricted = await search_knowledge("CANARY-RESTRICTED-KEY-7741 ceremony", role="analyst")
    assert all(hit["doc_id"] != "hr-comp-2026" for hit in viewer["hits"])
    assert any(hit["doc_id"] == "hr-comp-2026" for hit in analyst["hits"])
    assert any(hit["doc_id"] == "sec-key-ceremony" for hit in admin["hits"])
    assert all(hit["doc_id"] != "sec-key-ceremony" for hit in analyst_restricted["hits"])


def test_direct_document_load_rechecks_access():
    hidden = documents_for("viewer", ["sec-key-ceremony", "policy-data-classification"])
    assert [doc["doc_id"] for doc in hidden] == ["policy-data-classification"]


@pytest.mark.asyncio
async def test_unrelated_query_does_not_invent_a_hit():
    result = await search_knowledge("zxqv quantum pottery kiln", role="viewer")
    assert result["hits"] == []
