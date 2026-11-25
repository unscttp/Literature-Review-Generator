"""Stage gates: what each stage must have done before its result is accepted.

A stage's answer is only a summary; the real work is in the run's folder (the
library, the outline, the sections). Each stage names one of these checks in
``config/workflow.json`` (``react.result_check``), and DGS runs it when the
model gives its final answer. A check returns None to accept the answer, or
what is still missing: DGS then gives that back to the model, which goes on
working. A stage that runs out of steps with work missing fails, with the
reason, instead of handing an unfinished result to the next stage; the run
can then be resumed with fresh steps.
"""

from __future__ import annotations

from collections.abc import Callable

from .tools import RunTools

MAX_IDS = 15


def _ids(papers) -> str:
    ids = [p["id"] for p in papers]
    shown = ", ".join(ids[:MAX_IDS])
    return shown + (f" and {len(ids) - MAX_IDS} more" if len(ids) > MAX_IDS else "")


def scope_done(tools: RunTools) -> str | None:
    if tools.scope() is None:
        return "The scope is not approved yet: submit it with scope_submit and wait for the user."
    return None


def search_done(tools: RunTools) -> str | None:
    if tools.library.counts()["total"] == 0:
        return (
            "The library is still empty: run the scope's queries with lit_search_openalex "
            "(and lit_search_arxiv where it fits). If they find nothing, broaden the keywords."
        )
    return None


def screen_done(tools: RunTools) -> str | None:
    counts = tools.library.counts()
    if counts["candidate"]:
        left = tools.library.papers("candidate")
        return (
            f"{counts['candidate']} of {counts['total']} papers are still candidates "
            f"({_ids(left)}); {counts['included']} are included and {counts['excluded']} excluded. "
            "Screen with the queue: library_next_candidates gives the next batch, decide it with "
            "one library_decide call, repeat; once enough papers are included, "
            "library_exclude_remaining excludes the rest with one reason."
        )
    if counts["included"] == 0:
        return (
            "No paper is included. Include the papers that meet the criteria with "
            "library_decide (decision include); excluded papers can be included again."
        )
    return None


def extract_done(tools: RunTools) -> str | None:
    missing = [p for p in tools.library.papers("included") if not p.get("notes")]
    if missing:
        return (
            f"{len(missing)} included papers have no notes yet ({_ids(missing)}). Read them with "
            "library_get and save notes with library_note (up to 10 papers per call)."
        )
    return None


def organize_done(tools: RunTools) -> str | None:
    missing = [p for p in tools.library.papers("included") if not p.get("themes")]
    if missing:
        return (
            f"{len(missing)} included papers have no theme yet ({_ids(missing)}). "
            "Assign each to 1-3 themes with library_tag."
        )
    return None


def outline_done(tools: RunTools) -> str | None:
    outline = tools.outline()
    if len(outline) < 2:
        return "No outline is saved yet: save the sections with review_set_outline."
    planned = {p for section in outline for p in section.get("papers", [])}
    missing = [p for p in tools.library.papers("included") if p["id"] not in planned]
    if missing:
        return (
            f"{len(missing)} included papers are not planned in any section ({_ids(missing)}). "
            "Add them to the papers of the sections that will discuss them and save the "
            "outline again."
        )
    return None


def write_done(tools: RunTools) -> str | None:
    written = {s["id"] for s in tools.sections.all()}
    missing = [s["id"] for s in tools.outline() if s["id"] not in written]
    if missing:
        return (
            f"These sections of the outline are not written yet: {', '.join(missing)}. "
            "Write each with review_write_section."
        )
    return None


def review_done(tools: RunTools) -> str | None:
    result = check(tools)
    blocking = [issue for issue in result["issues"] if issue["blocking"]]
    if blocking:
        return (
            "The review is not finished; review_check reports: "
            + "; ".join(_describe(issue) for issue in blocking)
            + ". Fix these, then answer again."
        )
    return None


def check(tools: RunTools) -> dict:
    from .report import check as check_report

    return check_report(tools.library, tools.sections, [s["id"] for s in tools.outline()])


def _describe(issue: dict) -> str:
    detail = issue.get("ids") or issue.get("sections") or []
    where = f" in {issue['section']}" if issue.get("section") else ""
    return f"{issue['kind']}{where}" + (f": {', '.join(detail[:MAX_IDS])}" if detail else "")


GATES: dict[str, Callable[[RunTools], str | None]] = {
    "scope_done": scope_done,
    "search_done": search_done,
    "screen_done": screen_done,
    "extract_done": extract_done,
    "organize_done": organize_done,
    "outline_done": outline_done,
    "write_done": write_done,
    "review_done": review_done,
}


def register_gates(engine, tools: RunTools) -> None:
    """Register every gate on a run's engine, bound to that run's tools."""
    for name, gate in GATES.items():
        engine.register_result_check(name, lambda context, result, gate=gate: gate(tools))
