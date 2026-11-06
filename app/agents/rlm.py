"""Recursive research over the catalog.

The planner writes a short Python filter, runs it in the sandbox, and checks
it against a declarative version of the same plan. Selected documents are then
summarized in batches. A batch that is still large is split and summarized by
another call. A failed branch is recorded and does not discard the branches
that succeeded.
"""

from __future__ import annotations

from app.auth.rbac import tool_allowed
from app.clock import rolling_year_start
from app.config import get_settings
from app.observability import note
from app.retrieval.service import catalog_for, documents_for
from app.security.validation import is_iso_date
from app.tools.sandbox import SandboxError, execute

ALLOWED_DEPARTMENTS = {"payments", "security", "retail", "platform", "people", "risk"}
ALLOWED_TYPES = {"incident", "runbook", "architecture", "specification", "policy", "meeting"}

ANALYSIS_CODE = """
counts = {}
for doc in docs:
    cause = doc.get("root_cause") or "unspecified"
    cause = str(cause).lower()
    if cause == "":
        cause = "unspecified"
    counts[cause] = counts.get(cause, 0) + 1
recurring = []
for cause in counts:
    count = counts.get(cause)
    if count >= 2:
        recurring.append(cause)
result["counts"] = counts
result["recurring"] = sorted(recurring)
result["total"] = len(docs)
"""


def build_plan(query: str, role: str) -> dict:
    text = query.lower()
    plan: dict = {
        "document_type": None,
        "department": None,
        "created_date_gte": None,
        "use_python": False,
        "reason": [],
        "role": role,
        "batch_size": get_settings().rlm_batch_size,
    }
    if any(word in text for word in ("outage", "incident", "failure", "failures")):
        plan["document_type"] = "incident"
        plan["reason"].append("keep incident reports")
    if "payment" in text:
        plan["department"] = "payments"
        plan["reason"].append("keep the payments namespace")
    if any(phrase in text for phrase in ("last year", "past year", "past 12", "last 12", "over the last")):
        plan["created_date_gte"] = rolling_year_start()
        plan["reason"].append(f"created on or after {plan['created_date_gte']}")
    if any(phrase in text for phrase in ("root cause", "recurring", "how many", "count", "trend")):
        plan["use_python"] = True
        plan["reason"].append("count root causes with the analysis tool")
    if not plan["reason"]:
        plan["reason"].append("no extra filter; inspect the visible catalog")
    return plan


def select_ids(catalog: list[dict], plan: dict) -> list[str]:
    chosen = []
    for doc in catalog:
        if plan.get("document_type") and doc.get("document_type") != plan["document_type"]:
            continue
        if plan.get("department") and doc.get("department") != plan["department"]:
            continue
        if plan.get("created_date_gte") and str(doc.get("created_date", "")) < plan["created_date_gte"]:
            continue
        chosen.append(doc["doc_id"])
    dates = {doc["doc_id"]: doc.get("created_date", "") for doc in catalog}
    return sorted(chosen, key=lambda doc_id: dates.get(doc_id, ""))


def render_plan_code(plan: dict) -> str:
    lines = ["selected = []", "for doc in catalog:"]
    document_type = plan.get("document_type")
    department = plan.get("department")
    created = plan.get("created_date_gte")
    if document_type in ALLOWED_TYPES:
        lines.append(f'    if doc.get("document_type") != "{document_type}":')
        lines.append("        continue")
    if department in ALLOWED_DEPARTMENTS:
        lines.append(f'    if doc.get("department") != "{department}":')
        lines.append("        continue")
    if created and is_iso_date(created):
        lines.append(f'    if doc.get("created_date") < "{created}":')
        lines.append("        continue")
    lines.append('    selected.append(doc.get("doc_id"))')
    lines.append('result["selected"] = selected')
    return "\n".join(lines)


async def run_rlm(query: str, role: str, state: dict) -> dict:
    activities: list[dict] = []

    async def record(detail: str, state_name: str = "research") -> None:
        activities.append(await note(state, "research_agent", state_name, detail))

    catalog = catalog_for(role)
    plan = build_plan(query, role)
    code = render_plan_code(plan)
    await record(
        f"Explored {len(catalog)} documents visible to this role. Filters: {', '.join(plan['reason'])}."
    )
    await record("Python search plan:\n" + code, "tool")
    try:
        executed = execute(code, catalog=catalog)
        selected = [item for item in executed.get("selected", []) if isinstance(item, str)]
        declarative = select_ids(catalog, plan)
        dates = {doc["doc_id"]: doc.get("created_date", "") for doc in catalog}
        selected = sorted(set(selected), key=lambda doc_id: dates.get(doc_id, ""))
        if selected != declarative:
            await record(
                "The sandbox selection did not match the declarative plan. Using the declarative plan.",
                "validation",
            )
            selected = declarative
    except SandboxError as exc:
        selected = select_ids(catalog, plan)
        await record(f"Python plan failed ({exc}). Used the declarative planner instead.", "error")

    documents = documents_for(role, selected)
    await record(f"Loaded {len(documents)} targeted documents after the access check.", "retrieval")

    analysis = None
    python_note = None
    if plan["use_python"]:
        if not tool_allowed(role, "python_analysis"):
            python_note = "Python analysis skipped because this role cannot run that tool"
            await record(python_note, "validation")
        else:
            slim = [
                {"doc_id": doc["doc_id"], "root_cause": doc.get("root_cause") or "", "title": doc["title"]}
                for doc in documents
            ]
            try:
                analysis = execute(ANALYSIS_CODE, docs=slim)
                await record(f"Python analysis counts: {analysis.get('counts')}", "tool")
            except SandboxError as exc:
                await record(f"Python analysis failed ({exc}). The narrative summary will continue.", "error")

    settings = get_settings()
    failures: list[str] = []
    batches = _batches(documents, plan["batch_size"])
    partials: list[str] = []
    for index, batch in enumerate(batches, start=1):
        await record(f"Batch {index} of {len(batches)} ({len(batch)} documents).", "research")
        partial = await summarize_branch(
            batch,
            query,
            depth=0,
            max_depth=settings.rlm_max_depth,
            char_limit=settings.rlm_char_limit,
            failures=failures,
            record=record,
        )
        if partial:
            partials.append(partial)
    summary = render_summary(partials, analysis, failures, python_note)
    return {
        "summary": summary,
        "documents": documents,
        "plan": plan,
        "plan_code": code,
        "analysis": analysis,
        "failures": failures,
        "activities": activities,
    }


async def summarize_branch(
    docs: list[dict],
    query: str,
    *,
    depth: int,
    max_depth: int,
    char_limit: int,
    failures: list[str],
    record,
) -> str:
    try:
        total_chars = sum(len(doc.get("text") or "") for doc in docs)
        if len(docs) > 1 and depth < max_depth and total_chars > char_limit:
            midpoint = max(1, len(docs) // 2)
            await record(
                f"Recursive sub-agent at depth {depth + 1} is splitting {len(docs)} documents.",
                "research",
            )
            left = await summarize_branch(
                docs[:midpoint],
                query,
                depth=depth + 1,
                max_depth=max_depth,
                char_limit=char_limit,
                failures=failures,
                record=record,
            )
            right = await summarize_branch(
                docs[midpoint:],
                query,
                depth=depth + 1,
                max_depth=max_depth,
                char_limit=char_limit,
                failures=failures,
                record=record,
            )
            return "\n".join(part for part in (left, right) if part)
        await record(f"Leaf sub-agent at depth {depth} is summarizing {len(docs)} document(s).", "research")
        return leaf_lines(docs, query)
    except Exception as exc:
        label = ", ".join(doc.get("doc_id", "?") for doc in docs)
        failures.append(f"{label}: {type(exc).__name__}")
        await record(f"Isolated a failed branch at depth {depth}: {label}.", "error")
        return ""


def leaf_lines(docs: list[dict], query: str) -> str:
    from app.agents.synthesize import evidence_snippet

    lines = []
    for doc in docs:
        if doc.get("force_fail"):
            raise RuntimeError(f"sub-agent failed on {doc.get('doc_id')}")
        snippet = evidence_snippet(doc.get("text") or "", query)
        cause = doc.get("root_cause") or "not recorded"
        lines.append(
            f"- {doc.get('created_date')} {doc.get('title')}: {snippet} "
            f"Root cause: {cause}. [doc:{doc.get('doc_id')}]"
        )
    return "\n".join(lines)


def render_summary(
    partials: list[str],
    analysis: dict | None,
    failures: list[str],
    python_note: str | None,
) -> str:
    lines = ["Summary of the documents selected by the research plan:"]
    if python_note:
        lines.append(python_note + ".")
    if analysis:
        lines.append("Root-cause counts from the Python analysis tool:")
        counts = analysis.get("counts") or {}
        for cause, count in sorted(counts.items(), key=lambda item: (-item[1], str(item[0]))):
            lines.append(f"- {cause}: {count}")
        recurring = analysis.get("recurring") or []
        if recurring:
            lines.append("Recurring root causes: " + ", ".join(str(item) for item in recurring) + ".")
        else:
            lines.append("No root cause met the recurring threshold of 2.")
    if partials:
        lines.extend(["", "Batch findings:", *partials])
    else:
        lines.append("No matching documents were available for this role and filter.")
    if failures:
        lines.append(
            "Some branches failed and were left out so the rest of the summary could still be returned: "
            + "; ".join(failures)
        )
    return "\n".join(lines)


def _batches(documents: list[dict], size: int) -> list[list[dict]]:
    size = max(1, size)
    return [documents[index : index + size] for index in range(0, len(documents), size)]
