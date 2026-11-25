"""The review's tools, as one DGS tool module per run.

Every run gets its own ``LocalToolModule`` bound to the run's folder, so a
tool can only ever touch that run's library and text. Which stage may use
which tool is decided by the allowances in ``config/allowances`` (DGS checks
them before every call); the tools themselves only check their arguments.

``scope.submit`` is the review's human check: it pauses the run until the
user approves the scope in the web interface. When the user asks for changes
instead, the tool returns the comment to the model, which revises the scope
and submits it again (the request is marked ``"on_reject": "continue"``).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

from workflow_core import LocalToolModule, ToolDefinition, register_skill, require_human_check

from .library import NOTE_FIELDS, Library, write_json
from .references import cited_ids
from .report import Sections, check
from .sources import SearchError, arxiv_search, openalex_search

SKILLS = ("literature-search", "screening-extraction", "review-organization", "review-writing")
LIST_LIMIT = 40

_YEAR = {"type": "integer", "minimum": 1500, "maximum": 2100}
_ID = {"type": "string", "pattern": "^P[0-9]{1,5}$"}
_SECTION = {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]{0,39}$"}
_TEXT = {"type": "string", "maxLength": 2000}


def _object(properties: dict, required=()) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def _strings(max_items: int, max_length: int = 400) -> dict:
    return {
        "type": "array",
        "items": {"type": "string", "minLength": 1, "maxLength": max_length},
        "maxItems": max_items,
    }


SCOPE_SUBMIT = ToolDefinition(
    "scope.submit",
    "low",
    description=(
        "Submit the review scope to the user for approval. The run pauses until the user "
        "decides. Returns approved true, or approved false with the user's feedback: then "
        "revise the scope accordingly and submit it again."
    ),
    input_schema=_object(
        {
            "title": {"type": "string", "minLength": 3, "maxLength": 200},
            "research_questions": {**_strings(6), "minItems": 1},
            "inclusion_criteria": {**_strings(10), "minItems": 1},
            "exclusion_criteria": _strings(10),
            "search_queries": {**_strings(20, 300), "minItems": 1},
            "from_year": _YEAR,
            "to_year": _YEAR,
            "notes": _TEXT,
        },
        ["title", "research_questions", "inclusion_criteria", "search_queries"],
    ),
)

_SEARCH_COMMON = {
    "query": {"type": "string", "minLength": 2, "maxLength": 300},
    "max_results": {"type": "integer", "minimum": 1, "maximum": 25},
    "from_year": _YEAR,
    "to_year": _YEAR,
}
SEARCH_OPENALEX = ToolDefinition(
    "lit.search_openalex",
    "medium",
    description=(
        "Search OpenAlex, an index of journal articles, conference papers, books and theses "
        "in all fields. Found papers are added to the review's library with ids (P1, P2 ...); "
        "the reply lists them briefly. English keywords find the most; language (ISO 639-1, "
        "e.g. 'zh') limits results to one language. sort: relevance, cited or recent."
    ),
    input_schema=_object(
        {
            **_SEARCH_COMMON,
            "sort": {"enum": ["relevance", "cited", "recent"]},
            "language": {"type": "string", "pattern": "^[a-z]{2}$"},
        },
        ["query"],
    ),
)
SEARCH_ARXIV = ToolDefinition(
    "lit.search_arxiv",
    "medium",
    description=(
        "Search arXiv preprints (physics, mathematics, computer science, statistics, "
        "quantitative biology and finance, economics, electrical engineering). Found papers "
        "are added to the library. Plain keywords are combined with AND; quote phrases. "
        "category is an arXiv category such as cs.CL. sort: relevance or recent."
    ),
    input_schema=_object(
        {
            **_SEARCH_COMMON,
            "sort": {"enum": ["relevance", "recent"]},
            "category": {"type": "string", "pattern": "^[a-z-]+(\\.[A-Za-z-]+)?$"},
        },
        ["query"],
    ),
)
LIBRARY_LIST = ToolDefinition(
    "library.list",
    "low",
    description=(
        "List papers in the library, briefly (id, title, first author, year, venue, status, "
        f"themes). Up to {LIST_LIMIT} per call; use offset for more. detail 'abstract' adds the "
        "first lines of each abstract."
    ),
    input_schema=_object(
        {
            "status": {"enum": ["all", "candidate", "included", "excluded"]},
            "theme": {"type": "string", "maxLength": 80},
            "detail": {"enum": ["brief", "abstract"]},
            "offset": {"type": "integer", "minimum": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": LIST_LIMIT},
        }
    ),
)
LIBRARY_GET = ToolDefinition(
    "library.get",
    "low",
    description="Full records of up to 8 papers: authors, venue, abstract, notes, themes.",
    input_schema=_object(
        {"ids": {"type": "array", "items": _ID, "minItems": 1, "maxItems": 8}}, ["ids"]
    ),
)
LIBRARY_DECIDE = ToolDefinition(
    "library.decide",
    "low",
    description=(
        "Record screening decisions, up to 100 per call: include or exclude papers (or put "
        "them back to candidate), each with a short reason that refers to the criteria. "
        "Every candidate must end up included or excluded."
    ),
    input_schema=_object(
        {
            "decisions": {
                "type": "array",
                "minItems": 1,
                "maxItems": 100,
                "items": _object(
                    {
                        "id": _ID,
                        "decision": {"enum": ["include", "exclude", "candidate"]},
                        "reason": {"type": "string", "maxLength": 300},
                    },
                    ["id", "decision"],
                ),
            }
        },
        ["decisions"],
    ),
)
EXCLUDE_REMAINING = ToolDefinition(
    "library.exclude_remaining",
    "low",
    description=(
        "Exclude every paper that is still a candidate, with one reason (for example 'E6: "
        "lower priority, enough papers included'). Use it once the papers to include have "
        "been chosen; it needs at least one included paper."
    ),
    input_schema=_object(
        {"reason": {"type": "string", "minLength": 3, "maxLength": 300}}, ["reason"]
    ),
)
LIBRARY_NOTE = ToolDefinition(
    "library.note",
    "low",
    description=(
        "Save extraction notes for up to 10 papers at once: for each, summary, method, data, "
        "findings, limitations, notes. Base them on the records you read; write 'not reported' "
        "rather than guessing."
    ),
    input_schema=_object(
        {
            "notes": {
                "type": "array",
                "minItems": 1,
                "maxItems": 10,
                "items": _object({"id": _ID, **{f: _TEXT for f in NOTE_FIELDS}}, ["id"]),
            }
        },
        ["notes"],
    ),
)
LIBRARY_TAG = ToolDefinition(
    "library.tag",
    "low",
    description=(
        "Assign papers to themes (1-5 short theme names each). Returns every theme with its papers."
    ),
    input_schema=_object(
        {
            "assignments": {
                "type": "array",
                "minItems": 1,
                "maxItems": 60,
                "items": _object(
                    {"id": _ID, "themes": {**_strings(5, 80), "minItems": 1}}, ["id", "themes"]
                ),
            }
        },
        ["assignments"],
    ),
)
SET_OUTLINE = ToolDefinition(
    "review.set_outline",
    "low",
    description=(
        "Save the review's outline: sections in order, each with an id (lowercase, digits, "
        "'-'), a title, what it covers and the papers it will cite. The abstract is written "
        "last and needs no entry."
    ),
    input_schema=_object(
        {
            "sections": {
                "type": "array",
                "minItems": 2,
                "maxItems": 15,
                "items": _object(
                    {
                        "id": _SECTION,
                        "title": {"type": "string", "minLength": 1, "maxLength": 200},
                        "purpose": _TEXT,
                        "papers": {"type": "array", "items": _ID, "maxItems": 40},
                    },
                    ["id", "title", "purpose"],
                ),
            }
        },
        ["sections"],
    ),
)
GET_OUTLINE = ToolDefinition(
    "review.outline",
    "low",
    description="Read the saved outline.",
    input_schema=_object({}),
)
WRITE_SECTION = ToolDefinition(
    "review.write_section",
    "low",
    description=(
        "Write or replace one section of the review in Markdown (no top-level heading; "
        "### subheadings are fine). Cite papers by library id in square brackets, [P12] or "
        "[P3, P7]; the reference list is generated from the library. Use section_id "
        "'abstract' for the abstract. position (1 = first) places a new section."
    ),
    input_schema=_object(
        {
            "section_id": _SECTION,
            "title": {"type": "string", "minLength": 1, "maxLength": 200},
            "content": {"type": "string", "minLength": 1, "maxLength": 16000},
            "position": {"type": "integer", "minimum": 1, "maximum": 30},
        },
        ["section_id", "title", "content"],
    ),
)
READ_SECTIONS = ToolDefinition(
    "review.read",
    "low",
    description=(
        "Without section_id: the sections written so far (id, title, words, cited papers). "
        "With section_id: that section's text."
    ),
    input_schema=_object({"section_id": _SECTION}),
)
DELETE_SECTION = ToolDefinition(
    "review.delete_section",
    "low",
    description="Delete a section.",
    input_schema=_object({"section_id": _SECTION}, ["section_id"]),
)
CHECK_REVIEW = ToolDefinition(
    "review.check",
    "low",
    description=(
        "Check the review: citations of unknown or not-included papers, included papers "
        "never cited, very short or missing sections, missing abstract."
    ),
    input_schema=_object({}),
)


class RunTools:
    """The tool handlers of one run, bound to its folder."""

    def __init__(
        self,
        folder: Path,
        request: dict,
        *,
        openalex_key: Callable[[], str | None] = lambda: None,
        openalex=openalex_search,
        arxiv=arxiv_search,
    ) -> None:
        self.folder = Path(folder)
        self.request = request
        self.library = Library(self.folder / "library.json")
        self.sections = Sections(self.folder / "sections.json")
        self.openalex_key = openalex_key
        self.search_functions = {"openalex": openalex, "arxiv": arxiv}

    # -- scope -----------------------------------------------------------------

    def scope(self) -> dict | None:
        try:
            return json.loads((self.folder / "scope.json").read_text("utf-8"))
        except (OSError, ValueError):
            return None

    def submit_scope(self, context, tool, args):
        scope = {key: args[key] for key in SCOPE_SUBMIT.input_schema["properties"] if key in args}
        details = {"kind": "scope_review", "scope": scope, "on_reject": "continue"}
        try:
            require_human_check(context, "scope.review", details)
        except PermissionError:
            comment = next(
                (
                    request.get("comment") or ""
                    for request in reversed(context.execution.human_checks)
                    if request["key"] == "scope.review" and request["status"] == "rejected"
                ),
                "",
            )
            return {
                "approved": False,
                "feedback": comment or "(The user asked for changes without a comment.)",
                "next": "Revise the scope following the feedback and call scope.submit again.",
            }
        write_json(self.folder / "scope.json", {**scope, "approved_at": time.time()})
        return {
            "approved": True,
            "next": "Answer with the approved scope as a short structured summary.",
        }

    # -- searching ---------------------------------------------------------------

    def search(self, source: str):
        def handler(context, tool, args):
            if source not in self.request.get("sources", ["openalex", "arxiv"]):
                return {"error": f"{source} is switched off for this review; use another source."}
            options = {
                "max_results": args.get("max_results", 15),
                "from_year": args.get("from_year", self.request.get("from_year")),
                "to_year": args.get("to_year", self.request.get("to_year")),
                "sort": args.get("sort", "relevance"),
            }
            if (
                options["from_year"]
                and options["to_year"]
                and options["from_year"] > options["to_year"]
            ):
                raise ValueError("from_year must not be after to_year.")
            if source == "openalex":
                options["language"] = args.get("language")
                options["api_key"] = self.openalex_key()
            else:
                options["category"] = args.get("category")
            query = args["query"].strip()
            try:
                records = self.search_functions[source](query, **options)
            except SearchError as exc:
                return {"query": query, "source": source, "error": str(exc)}
            papers = self.library.add(records, query=query, source=source)
            reply = {
                "query": query,
                "source": source,
                "found": len(papers),
                "new": sum(p["new"] for p in papers),
                "library": self.library.counts()["total"],
                "papers": papers,
            }
            if not papers:
                reply["note"] = "Nothing found: try broader or different keywords."
            return reply

        return handler

    # -- the library ---------------------------------------------------------------

    def list_papers(self, context, tool, args):
        papers = self.library.papers(args.get("status", "all"))
        if args.get("theme"):
            papers = [p for p in papers if args["theme"] in (p.get("themes") or [])]
        offset, limit = args.get("offset", 0), args.get("limit", LIST_LIMIT)
        page = papers[offset : offset + limit]
        reply = {
            "counts": self.library.counts(),
            "matching": len(papers),
            "papers": [Library.brief(p, args.get("detail") == "abstract") for p in page],
        }
        if offset + limit < len(papers):
            reply["next_offset"] = offset + limit
        return reply

    def get_papers(self, context, tool, args):
        found, missing = [], []
        for paper_id in args["ids"]:
            try:
                found.append(self.library.full(paper_id))
            except KeyError:
                missing.append(paper_id)
        return {"papers": found, **({"unknown": missing} if missing else {})}

    def decide(self, context, tool, args):
        counts = self.library.decide(args["decisions"])
        reply = {"counts": counts}
        if counts["candidate"]:
            left = [p["id"] for p in self.library.papers("candidate")][:20]
            reply["still_candidates"] = left
        return reply

    def exclude_remaining(self, context, tool, args):
        if not self.library.papers("included"):
            raise ValueError("No paper is included yet: include the relevant papers first.")
        left = self.library.papers("candidate")
        if left:
            self.library.decide(
                [{"id": p["id"], "decision": "exclude", "reason": args["reason"]} for p in left]
            )
        return {"excluded": len(left), "counts": self.library.counts()}

    def _require_included(self, ids, what: str) -> None:
        """Refuse papers that are not included: later stages work on the included set."""
        status = {p["id"]: p["status"] for p in self.library.papers()}
        unknown = sorted({i for i in ids if i not in status})
        if unknown:
            raise KeyError(f"Unknown paper ids: {', '.join(unknown)}. Nothing was saved.")
        wrong = sorted({f"{i} ({status[i]})" for i in ids if status[i] != "included"})
        if wrong:
            raise ValueError(
                f"Only included papers can {what}; not included: {', '.join(wrong)}. "
                "Nothing was saved. Screening decides which papers are included."
            )

    def note(self, context, tool, args):
        self._require_included([entry["id"] for entry in args["notes"]], "get notes")
        saved = [
            self.library.note(entry["id"], {k: v for k, v in entry.items() if k != "id"})["id"]
            for entry in args["notes"]
        ]
        return {
            "saved": saved,
            "with_notes": sum(bool(p.get("notes")) for p in self.library.papers()),
        }

    def tag(self, context, tool, args):
        self._require_included([a["id"] for a in args["assignments"]], "get themes")
        reply = self.library.tag(args["assignments"])
        untagged = [p["id"] for p in self.library.papers("included") if not p.get("themes")]
        if untagged:
            reply["included_without_themes"] = untagged
        return reply

    # -- the text --------------------------------------------------------------------

    def outline(self) -> list[dict]:
        try:
            return json.loads((self.folder / "outline.json").read_text("utf-8"))["sections"]
        except (OSError, ValueError, KeyError):
            return []

    def set_outline(self, context, tool, args):
        ids = [s["id"] for s in args["sections"]]
        if len(set(ids)) != len(ids):
            raise ValueError("Section ids must be unique.")
        planned = [p for s in args["sections"] for p in s.get("papers", [])]
        self._require_included(planned, "be planned in the outline")
        write_json(self.folder / "outline.json", {"sections": args["sections"]})
        reply = {"saved": ids}
        missing = [p["id"] for p in self.library.papers("included") if p["id"] not in planned]
        if missing:
            reply["included_not_planned"] = missing
        return reply

    def get_outline(self, context, tool, args):
        return {"sections": self.outline()}

    def write_section(self, context, tool, args):
        self._require_included(cited_ids(args["content"]), "be cited")
        summary = self.sections.write(
            args["section_id"], args["title"], args["content"], args.get("position")
        )
        written = next(s for s in summary if s["id"] == args["section_id"])
        return {"saved": args["section_id"], "words": written["words"], "sections": summary}

    def read_sections(self, context, tool, args):
        if args.get("section_id"):
            section = next((s for s in self.sections.all() if s["id"] == args["section_id"]), None)
            if section is None:
                raise KeyError(f"No section {args['section_id']!r}.")
            return section
        return {"sections": self.sections.summary(), "outline": [s["id"] for s in self.outline()]}

    def delete_section(self, context, tool, args):
        return {"sections": self.sections.delete(args["section_id"])}

    def check(self, context, tool, args):
        return check(self.library, self.sections, [s["id"] for s in self.outline()])

    # -- the module --------------------------------------------------------------------

    def module(self, skills_dir: Path) -> LocalToolModule:
        module = LocalToolModule()
        handlers = [
            (SCOPE_SUBMIT, self.submit_scope),
            (SEARCH_OPENALEX, self.search("openalex")),
            (SEARCH_ARXIV, self.search("arxiv")),
            (LIBRARY_LIST, self.list_papers),
            (LIBRARY_GET, self.get_papers),
            (LIBRARY_DECIDE, self.decide),
            (EXCLUDE_REMAINING, self.exclude_remaining),
            (LIBRARY_NOTE, self.note),
            (LIBRARY_TAG, self.tag),
            (SET_OUTLINE, self.set_outline),
            (GET_OUTLINE, self.get_outline),
            (WRITE_SECTION, self.write_section),
            (READ_SECTIONS, self.read_sections),
            (DELETE_SECTION, self.delete_section),
            (CHECK_REVIEW, self.check),
        ]
        for definition, handler in handlers:
            module.register(definition, handler)
        for name in SKILLS:
            register_skill(module, Path(skills_dir) / name)
        return module


TOOL_NAMES = [
    tool.name
    for tool in (
        SCOPE_SUBMIT,
        SEARCH_OPENALEX,
        SEARCH_ARXIV,
        LIBRARY_LIST,
        LIBRARY_GET,
        LIBRARY_DECIDE,
        EXCLUDE_REMAINING,
        LIBRARY_NOTE,
        LIBRARY_TAG,
        SET_OUTLINE,
        GET_OUTLINE,
        WRITE_SECTION,
        READ_SECTIONS,
        DELETE_SECTION,
        CHECK_REVIEW,
    )
]
