"""The interface is complete in English and Simplified Chinese."""

import json
import re
import unittest

from tests.support import ROOT
from lrg.tools import SKILLS

WEB = ROOT / "web"


def keys(tree, prefix=""):
    found = set()
    for key, value in tree.items():
        found |= keys(value, f"{prefix}{key}.") if isinstance(value, dict) else {prefix + key}
    return found


class I18nTests(unittest.TestCase):
    def setUp(self):
        self.en = json.loads((WEB / "i18n" / "en.json").read_text("utf-8"))
        self.zh = json.loads((WEB / "i18n" / "zh-CN.json").read_text("utf-8"))

    def test_same_keys_in_both_languages(self):
        self.assertEqual(keys(self.en), keys(self.zh))

    def test_every_key_used_exists(self):
        known = keys(self.en)
        html = (WEB / "index.html").read_text("utf-8")
        used = set(re.findall(r'data-i18n(?:-placeholder)?="([\w.-]+)"', html))
        for name in ("app.js", "viewer.js"):
            used |= set(re.findall(r'\bt\("([\w.-]+)"', (WEB / name).read_text("utf-8")))
        self.assertEqual(used - known, set())

    def test_names_for_stages_skills_and_graph_nodes(self):
        workflow = json.loads((ROOT / "config" / "workflow.json").read_text("utf-8"))
        for node in workflow["nodes"]:
            self.assertIn(node["id"], self.zh["stages"])
        for skill in SKILLS:
            self.assertIn(skill, self.zh["skills"])
            for path in (ROOT / "skills" / skill / "graphs").glob("*.json"):
                if path.name.endswith(".meta.json"):
                    continue
                self.assertIn(path.stem, self.zh["skills"]["graphs"])
                for node in json.loads(path.read_text("utf-8"))["graph"]["nodes"]:
                    self.assertIn(node["id"], self.zh["graphNodes"])
        for kind in (
            "unknown_citation",
            "cites_not_included",
            "included_not_cited",
            "short_section",
            "missing_abstract",
            "missing_sections",
        ):
            self.assertIn(kind, self.zh["report"]["issues"])

    def test_options_are_translated(self):
        from lrg.pipeline import LANGUAGES, REVIEW_TYPES, SOURCES
        from lrg.references import STYLES

        for name, values in (
            ("language", LANGUAGES),
            ("style", STYLES),
            ("review_type", REVIEW_TYPES),
            ("sources", SOURCES),
        ):
            for value in values:
                self.assertIn(value, self.zh["options"][name])
                self.assertIn(value, self.en["options"][name])


if __name__ == "__main__":
    unittest.main()
