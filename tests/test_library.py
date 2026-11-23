"""The paper library and the review text."""

import tempfile
import unittest
from pathlib import Path

from tests.support import ROOT  # noqa: F401
from lrg.library import Library
from lrg.report import Sections, check, words


class LibraryTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.library = Library(self.folder / "library.json")

    def test_duplicates_are_merged(self):
        first = self.library.add(
            [
                {"title": "Irony: A Study", "doi": "10.1/X", "authors": ["A B"]},
                {"title": "Preprint", "arxiv_id": "2301.1"},
                {"title": ""},
            ],
            query="q1",
            source="openalex",
        )
        self.assertEqual([p["id"] for p in first], ["P1", "P2"])
        second = self.library.add(
            [
                {"title": "irony - a study!", "venue": "J"},  # same title
                {"title": "Published", "doi": "10.1/x"},  # same DOI, other case
                {"title": "Other", "arxiv_id": "2301.1"},
            ],  # same arXiv id
            query="q2",
            source="arxiv",
        )
        self.assertEqual(
            [(p["id"], p["new"]) for p in second], [("P1", False), ("P1", False), ("P2", False)]
        )
        paper = self.library.get("P1")
        self.assertEqual(paper["venue"], "J")  # gaps filled from the other source
        self.assertEqual(len(paper["found_by"]), 2)  # one entry per source and query
        self.assertEqual(
            self.library.counts(),
            {"candidate": 2, "included": 0, "excluded": 0, "total": 2, "searches": 2},
        )
        self.assertEqual(Library(self.folder / "library.json").counts()["total"], 2)  # saved

    def test_decisions_notes_themes(self):
        self.library.add([{"title": "A"}, {"title": "B"}], query="q", source="openalex")
        with self.assertRaises(KeyError):
            self.library.decide([{"id": "P9", "decision": "include", "reason": ""}])
        counts = self.library.decide([{"id": "P1", "decision": "include", "reason": "x" * 999}])
        self.assertEqual(counts["included"], 1)
        self.assertEqual(len(self.library.get("P1")["reason"]), 300)
        self.library.note("P1", {"summary": "S", "unknown": "ignored", "method": "M" * 5000})
        notes = self.library.get("P1")["notes"]
        self.assertEqual(set(notes), {"summary", "method"})
        self.assertEqual(len(notes["method"]), 2000)
        themes = self.library.tag(
            [{"id": "P1", "themes": ["T1", "T2"]}, {"id": "P2", "themes": ["T1"]}]
        )
        self.assertEqual(themes["themes"], {"T1": ["P1", "P2"], "T2": ["P1"]})


class SectionTests(unittest.TestCase):
    def test_sections_and_check(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        library = Library(Path(folder.name) / "library.json")
        library.add([{"title": "A"}, {"title": "B"}, {"title": "C"}], query="q", source="openalex")
        library.decide(
            [
                {"id": "P1", "decision": "include", "reason": ""},
                {"id": "P2", "decision": "include", "reason": ""},
                {"id": "P3", "decision": "exclude", "reason": ""},
            ]
        )
        sections = Sections(Path(folder.name) / "sections.json")
        with self.assertRaises(ValueError):
            sections.write("Bad Id", "T", "x")
        with self.assertRaises(ValueError):
            sections.write("long", "T", "x" * 20000)
        sections.write("intro", "Intro", "word " * 50 + "[P1] [P3] [P7]")
        sections.write("abstract", "Abstract", "short")
        sections.write("end", "End", "word " * 50, position=1)
        self.assertEqual([s["id"] for s in sections.all()], ["abstract", "end", "intro"])
        result = check(library, sections, ["intro", "themes"])
        kinds = {issue["kind"]: issue for issue in result["issues"]}
        self.assertEqual(kinds["unknown_citation"]["ids"], ["P7"])
        self.assertEqual(kinds["cites_not_included"]["ids"], ["P3"])
        self.assertEqual(kinds["included_not_cited"]["ids"], ["P2"])
        self.assertEqual(kinds["short_section"]["section"], "abstract")
        self.assertEqual(kinds["missing_sections"]["sections"], ["themes"])
        sections.delete("abstract")
        self.assertIn("missing_abstract", {i["kind"] for i in check(library, sections)["issues"]})

    def test_words(self):
        self.assertEqual(words("Free indirect discourse, it's here."), 5)
        self.assertEqual(words("自由间接引语 [P1]"), 7)


if __name__ == "__main__":
    unittest.main()
