"""The workflow, allowances, skills and sample graphs fit together."""

import json
import re
import unittest

from tests.support import ROOT
from workflow_core import AllowanceRegistry, LocalToolModule, register_skill
from workflow_skills import load_skill_graph

from lrg.tools import SKILLS, TOOL_NAMES

CONFIG = ROOT / "config"


def allowances():
    registry = AllowanceRegistry()
    for path in sorted((CONFIG / "allowances").glob("*.json")):
        registry.load(path)
    return registry


def skill_tools():
    module = LocalToolModule()
    for name in SKILLS:
        register_skill(module, ROOT / "skills" / name)
    return {tool.name for tool in module.list_tools()}


def workflow():
    return json.loads((CONFIG / "workflow.json").read_text("utf-8"))


def function(name):
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name)


class ConfigTests(unittest.TestCase):
    def test_eight_stages_in_a_chain(self):
        document = workflow()
        ids = [node["id"] for node in document["nodes"]]
        self.assertEqual(
            ids, ["scope", "search", "screen", "extract", "organize", "outline", "write", "review"]
        )
        self.assertEqual(
            [(e["from"], e["to"]) for e in document["edges"]], list(zip(ids, ids[1:], strict=False))
        )

    def test_every_allowed_action_exists(self):
        known = set(TOOL_NAMES) | skill_tools()
        for allowance in allowances().sets.values():
            for action in allowance.actions:
                self.assertIn(action.removeprefix("tool:"), known, f"{allowance.id}: {action}")

    def test_instructions_only_name_allowed_tools(self):
        registry = allowances()
        known = {function(name): name for name in set(TOOL_NAMES) | skill_tools()}
        graphs = [workflow()] + [
            load_skill_graph(ROOT / "skills" / skill, path.stem)["graph"]
            for skill in SKILLS
            for path in (ROOT / "skills" / skill / "graphs").glob("*.json")
        ]
        for graph in graphs:
            for node in graph["nodes"]:
                allowed = {
                    a.removeprefix("tool:") for a in registry.resolve(node["allowance"]).actions
                }
                for word in re.findall(
                    r"[a-z][a-z0-9-]*_[a-z0-9_-]+", node["config"]["instruction"]
                ):
                    if word in known:
                        self.assertIn(known[word], allowed, f"{node['id']} names {word}")

    def test_skill_graphs_fit_the_stage_that_runs_them(self):
        registry = allowances()
        stage_of = {node["allowance"]: node["id"] for node in workflow()["nodes"]}
        for skill in SKILLS:
            runners = [
                a for a in registry.sets.values() if f"tool:skill.{skill}.run_graph" in a.actions
            ]
            self.assertEqual(len(runners), 1, skill)
            parent = runners[0]
            self.assertIn(parent.id, stage_of)
            graphs = list((ROOT / "skills" / skill / "graphs").glob("*.json"))
            self.assertEqual(len(graphs), 1, f"{skill} has one sample graph")
            graph = load_skill_graph(ROOT / "skills" / skill, graphs[0].stem)
            for node in graph["graph"]["nodes"]:
                registry.resolve(node["allowance"]).assert_subset_of(parent)
                self.assertEqual(node["type"], "stage")

    def test_sample_graph_files_match_their_script(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "skill_graphs", ROOT / "scripts" / "skill_graphs.py"
        )
        script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(script)
        for graph in script.GRAPHS:
            self.assertEqual(
                script.path(graph).read_text("utf-8"),
                script.render(graph),
                "run python scripts/skill_graphs.py",
            )

    def test_skill_references_exist(self):
        text = (CONFIG / "workflow.json").read_text("utf-8")
        for skill in SKILLS:
            body = (ROOT / "skills" / skill / "SKILL.md").read_text("utf-8")
            for reference in re.findall(r"`(references/[\w.-]+)`", body):
                self.assertTrue(
                    (ROOT / "skills" / skill / reference).is_file(), f"{skill}/{reference}"
                )
        for reference in set(re.findall(r"references/[\w.-]+\.md", text)):
            self.assertTrue(
                any((ROOT / "skills" / s / reference).is_file() for s in SKILLS), reference
            )


if __name__ == "__main__":
    unittest.main()
