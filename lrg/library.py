"""The paper library of one review run: every paper the searches found.

Searches add papers here and give each one a short id (``P1``, ``P2`` ...).
The model works with those ids: it screens papers (``include`` or
``exclude`` with a reason), adds extraction notes and themes, and cites them
as ``[P12]`` in the text. The reference list is later built from these
records, never from the model's memory, so a cited paper always exists.

The library is a JSON file in the run folder, written atomically. One run's
stages run one at a time, but the web interface reads it meanwhile, so all
access goes through a lock.
"""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
import threading
import unicodedata
from pathlib import Path

STATUSES = ("candidate", "included", "excluded")
NOTE_FIELDS = ("summary", "method", "data", "findings", "limitations", "notes")
NOTE_CHARS = 2000
ABSTRACT_CHARS = 2500
BRIEF_ABSTRACT_CHARS = 300


def _normal_title(title: str) -> str:
    text = unicodedata.normalize("NFKC", title or "").casefold()
    return re.sub(r"[\W_]+", "", text)


def _clip(text: str | None, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def first_author(paper: dict) -> str:
    authors = paper.get("authors") or []
    if not authors:
        return ""
    return authors[0] + (" et al." if len(authors) > 1 else "")


def write_json(path: Path, data) -> None:
    """Write JSON atomically: readers never see half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=1)
        os.replace(name, path)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


class Library:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        try:
            self._data = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            self._data = {"next": 1, "papers": [], "searches": []}

    # -- reading ---------------------------------------------------------------

    def papers(self, status: str | None = None) -> list[dict]:
        with self._lock:
            return [
                copy.deepcopy(p)
                for p in self._data["papers"]
                if status in (None, "all") or p["status"] == status
            ]

    def get(self, paper_id: str) -> dict:
        with self._lock:
            for paper in self._data["papers"]:
                if paper["id"] == paper_id:
                    return copy.deepcopy(paper)
        raise KeyError(f"No paper {paper_id!r} in the library.")

    def ids(self) -> set[str]:
        with self._lock:
            return {p["id"] for p in self._data["papers"]}

    def searches(self) -> list[dict]:
        with self._lock:
            return copy.deepcopy(self._data["searches"])

    def counts(self) -> dict:
        with self._lock:
            counts = {status: 0 for status in STATUSES}
            for paper in self._data["papers"]:
                counts[paper["status"]] += 1
            counts["total"] = len(self._data["papers"])
            counts["searches"] = len(self._data["searches"])
            return counts

    def snapshot(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._data)

    @staticmethod
    def brief(paper: dict, abstract: bool = False) -> dict:
        view = {
            "id": paper["id"],
            "title": paper["title"],
            "first_author": first_author(paper),
            "year": paper.get("year"),
            "venue": paper.get("venue"),
            "type": paper.get("type"),
            "cited_by": paper.get("cited_by"),
            "status": paper["status"],
        }
        if paper.get("reason"):
            view["reason"] = paper["reason"]
        if paper.get("themes"):
            view["themes"] = paper["themes"]
        if paper.get("notes"):
            view["has_notes"] = True
        if abstract:
            view["abstract"] = _clip(paper.get("abstract"), BRIEF_ABSTRACT_CHARS)
        return view

    # -- changing ----------------------------------------------------------------

    def _save(self) -> None:
        write_json(self.path, self._data)

    def _find_duplicate(self, record: dict) -> dict | None:
        doi = (record.get("doi") or "").lower()
        arxiv = record.get("arxiv_id")
        title = _normal_title(record.get("title", ""))
        for paper in self._data["papers"]:
            if doi and (paper.get("doi") or "").lower() == doi:
                return paper
            if arxiv and paper.get("arxiv_id") == arxiv:
                return paper
            if title and _normal_title(paper["title"]) == title:
                return paper
        return None

    def add(self, records: list[dict], *, query: str, source: str) -> list[dict]:
        """Add search results; returns each one as ``(paper, new)`` brief views."""
        added = []
        with self._lock:
            new_count = 0
            for record in records:
                if not (record.get("title") or "").strip():
                    continue
                paper = self._find_duplicate(record)
                new = paper is None
                if new:
                    paper = {
                        **record,
                        "id": f"P{self._data['next']}",
                        "status": "candidate",
                        "found_by": [],
                    }
                    self._data["next"] += 1
                    self._data["papers"].append(paper)
                    new_count += 1
                else:  # fill gaps from the other source (an arXiv preprint's DOI ...)
                    for key, value in record.items():
                        if value and not paper.get(key):
                            paper[key] = value
                hit = {"source": source, "query": query}
                if hit not in paper["found_by"]:
                    paper["found_by"].append(hit)
                added.append({**self.brief(paper), "new": new})
            self._data["searches"].append(
                {"source": source, "query": query, "found": len(added), "new": new_count}
            )
            self._save()
        return added

    def decide(self, decisions: list[dict]) -> dict:
        with self._lock:
            by_id = {p["id"]: p for p in self._data["papers"]}
            unknown = [d.get("id") for d in decisions if d.get("id") not in by_id]
            if unknown:
                raise KeyError(f"Unknown paper ids: {', '.join(map(str, unknown))}.")
            for decision in decisions:
                if decision["decision"] not in ("include", "exclude", "candidate"):
                    raise ValueError("decision must be include, exclude or candidate.")
                paper = by_id[decision["id"]]
                paper["status"] = {
                    "include": "included",
                    "exclude": "excluded",
                    "candidate": "candidate",
                }[decision["decision"]]
                paper["reason"] = _clip(decision.get("reason"), 300)
            self._save()
            return self.counts()

    def note(self, paper_id: str, notes: dict) -> dict:
        with self._lock:
            paper = next((p for p in self._data["papers"] if p["id"] == paper_id), None)
            if paper is None:
                raise KeyError(f"No paper {paper_id!r} in the library.")
            kept = paper.setdefault("notes", {})
            for field in NOTE_FIELDS:
                if notes.get(field):
                    kept[field] = _clip(str(notes[field]), NOTE_CHARS)
            self._save()
            return {"id": paper_id, "notes": copy.deepcopy(kept)}

    def tag(self, assignments: list[dict]) -> dict:
        with self._lock:
            by_id = {p["id"]: p for p in self._data["papers"]}
            unknown = [a.get("id") for a in assignments if a.get("id") not in by_id]
            if unknown:
                raise KeyError(f"Unknown paper ids: {', '.join(map(str, unknown))}.")
            for assignment in assignments:
                themes = [_clip(str(t), 80) for t in assignment.get("themes") or [] if str(t)]
                by_id[assignment["id"]]["themes"] = themes[:5]
            self._save()
            themes: dict[str, list[str]] = {}
            for paper in self._data["papers"]:
                for theme in paper.get("themes") or []:
                    themes.setdefault(theme, []).append(paper["id"])
            return {"themes": themes}

    def full(self, paper_id: str) -> dict:
        """One paper for the model: everything, with the abstract cut to a sane length."""
        paper = self.get(paper_id)
        paper["abstract"] = _clip(paper.get("abstract"), ABSTRACT_CHARS)
        paper.pop("found_by", None)
        return paper
