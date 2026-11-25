"""The review text: sections the model writes, and the finished report.

``write`` stores one section (Markdown with ``[P12]`` citations) in the run's
``sections.json``. ``build`` turns the sections into the finished report:
citations in the chosen style and a reference list generated from the
library, plus a BibTeX file. It is deterministic and runs again whenever the
report is opened, so the report always matches the sections and the library.
``check`` finds what a reviewer would flag: citations of unknown or excluded
papers, included papers nobody cites, empty or missing sections.
"""

from __future__ import annotations

import copy
import json
import re
import threading
from pathlib import Path

from .library import Library, write_json
from .references import Citations, bibtex, cited_ids, heading

# Issues that make a review unfinished; the others are warnings.
BLOCKING = {"unknown_citation", "cites_not_included", "missing_sections", "missing_abstract"}
SECTION_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
MAX_SECTION_CHARS = 16000
WORD = re.compile(r"[㐀-鿿]|[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*")


def words(text: str) -> int:
    """Words, counting each Chinese character as one (as Chinese word counts do)."""
    return len(WORD.findall(text or ""))


class Sections:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        try:
            self._data = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            self._data = {"sections": []}

    def all(self) -> list[dict]:
        with self._lock:
            return copy.deepcopy(self._data["sections"])

    def write(self, section_id: str, title: str, content: str, position: int | None = None):
        if not SECTION_ID.match(section_id):
            raise ValueError("section_id: lowercase letters, digits and '-', up to 40 characters.")
        if len(content) > MAX_SECTION_CHARS:
            raise ValueError(
                f"The section is {len(content)} characters; the limit is {MAX_SECTION_CHARS}. "
                "Split it into two sections."
            )
        with self._lock:
            sections = self._data["sections"]
            existing = next((s for s in sections if s["id"] == section_id), None)
            if existing is None:
                existing = {"id": section_id}
                sections.append(existing)
            existing.update(title=title.strip(), content=content.strip())
            if position is not None:
                sections.remove(existing)
                sections.insert(max(0, min(position - 1, len(sections))), existing)
            # The abstract always comes first.
            sections.sort(key=lambda s: s["id"] != "abstract")
            write_json(self.path, self._data)
            return self.summary()

    def delete(self, section_id: str) -> list[dict]:
        with self._lock:
            before = len(self._data["sections"])
            self._data["sections"] = [s for s in self._data["sections"] if s["id"] != section_id]
            if len(self._data["sections"]) == before:
                raise KeyError(f"No section {section_id!r}.")
            write_json(self.path, self._data)
            return self.summary()

    def summary(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "id": s["id"],
                    "title": s["title"],
                    "words": words(s["content"]),
                    "cites": cited_ids(s["content"]),
                }
                for s in self._data["sections"]
            ]


def check(library: Library, sections: Sections, outline_ids: list[str] | None = None) -> dict:
    papers = {p["id"]: p for p in library.papers()}
    issues: list[dict] = []
    cited: set[str] = set()
    all_sections = sections.all()
    for section in all_sections:
        ids = cited_ids(section["content"])
        cited.update(ids)
        unknown = [i for i in ids if i not in papers]
        if unknown:
            issues.append({"kind": "unknown_citation", "section": section["id"], "ids": unknown})
        not_included = [i for i in ids if i in papers and papers[i]["status"] != "included"]
        if not_included:
            issues.append(
                {"kind": "cites_not_included", "section": section["id"], "ids": not_included}
            )
        if words(section["content"]) < 40:
            issues.append({"kind": "short_section", "section": section["id"]})
    uncited = [i for i, p in papers.items() if p["status"] == "included" and i not in cited]
    if uncited:
        issues.append({"kind": "included_not_cited", "ids": uncited})
    present = {s["id"] for s in all_sections}
    if "abstract" not in present:
        issues.append({"kind": "missing_abstract"})
    missing = [i for i in outline_ids or [] if i not in present]
    if missing:
        issues.append({"kind": "missing_sections", "sections": missing})
    for issue in issues:
        issue["blocking"] = issue["kind"] in BLOCKING
    return {
        "ok": not issues,
        # A review is complete when nothing blocking is left: every citation is an
        # included paper, every planned section and the abstract are written.
        "complete": not any(issue["blocking"] for issue in issues),
        "issues": issues,
        "sections": len(all_sections),
        "words": sum(words(s["content"]) for s in all_sections),
        "cited": len(cited & set(papers)),
        "included": sum(p["status"] == "included" for p in papers.values()),
    }


def build(library: Library, sections: Sections, *, style: str, language: str, title: str) -> dict:
    """The finished report: Markdown text, BibTeX and what was cited."""
    papers = {p["id"]: p for p in library.papers()}
    citations = Citations(papers, style)
    parts = [f"# {title}".strip()]
    for section in sections.all():
        body = citations.render(section["content"])
        parts.append(f"## {section['title']}\n\n{body}")
    references = citations.reference_list()
    if references:
        listing = "\n\n".join(references)
        parts.append(f"## {heading(style, language)}\n\n{listing}")
    cited = [papers[i] for i in citations.order]
    return {
        "markdown": "\n\n".join(parts) + "\n",
        "bibtex": bibtex(cited),
        "cited": citations.order,
        "words": sum(words(s["content"]) for s in sections.all()),
    }
