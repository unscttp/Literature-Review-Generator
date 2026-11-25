"""The eight-stage workflow, end to end, with a scripted model."""

import json
import tempfile
from pathlib import Path

from tests.support import CHOICE, LABEL, ServiceCase


class PipelineTests(ServiceCase):
    def test_full_review(self):
        service = self.make_service()
        run = service.create({"topic": "Irony in Jane Austen", "style": "gbt7714"})
        summary = self.wait(run["id"])
        self.assertEqual(summary["status"], "waiting")
        [approval] = summary["approvals"]
        self.assertEqual((approval["kind"], approval["can_revise"]), ("scope_review", True))
        self.assertEqual(approval["scope"]["title"], "Irony in Jane Austen")

        # Asking for changes sends the comment back; the model revises and resubmits.
        service.decide(run["id"], approval["id"], False, "Add Chinese criticism")
        summary = self.wait(run["id"])
        [approval] = summary["approvals"]
        self.assertEqual(approval["scope"]["notes"], "Revised: Add Chinese criticism")
        service.decide(run["id"], approval["id"], True)
        summary = self.wait(run["id"])
        self.assertEqual(summary["status"], "completed", summary.get("error"))

        self.assertEqual(summary["scope"]["notes"], "Revised: Add Chinese criticism")
        self.assertEqual(len(summary["stages"]), 8)
        self.assertEqual(summary["counts"]["included"], 2)
        # The rules reach every node, also the skill graph's.
        self.assertTrue(all("Never invent literature" in system for _, system in self.model.calls))
        self.assertIn("coverage", {node for node, _ in self.model.calls})

        report = service.report(run["id"])
        self.assertIn("[1]", report["markdown"])
        self.assertIn("## References", report["markdown"])
        self.assertTrue(report["check"]["ok"], report["check"])
        folder = service.folder(run["id"])
        self.assertTrue(
            (folder / "report.md").read_text("utf-8").startswith("# Irony in Jane Austen")
        )
        self.assertIn("@article{example2015irony", (folder / "references.bib").read_text("utf-8"))

        graph = service.graph(run["id"])
        root, child = graph["graphs"]
        self.assertEqual([n["status"] for n in root["nodes"]], ["completed"] * 8)
        self.assertEqual(child["parent"]["node"], "search")
        self.assertEqual(child["title"], "english-literature")
        self.assertEqual({n["status"] for n in child["nodes"]}, {"completed"})
        # DGS recorded the graph's run in the installed skill.
        meta = service.skills_dir / "literature-search" / "graphs" / "english-literature.meta.json"
        meta = json.loads(meta.read_text())
        self.assertEqual((meta["last_run"]["outcome"], meta["runs"]["completed"]), ("completed", 1))
        self.assertEqual(meta["last_run"]["environment"]["host"]["model"], LABEL)
        # The review records its model (never the key) and runs with it.
        record = json.loads((folder / "run.json").read_text())
        self.assertEqual((record["model"], record["model_choice"]), (LABEL, CHOICE))
        self.assertNotIn("sk-test", (folder / "run.json").read_text())
        self.assertEqual(self.chosen[-1], CHOICE)


class RunControlTests(ServiceCase):
    def approve(self, run_id):
        summary = self.wait(run_id)
        self.service.decide(run_id, summary["approvals"][0]["id"], True)

    def test_requests_are_validated(self):
        from lrg.pipeline import RunError

        service = self.make_service()
        for bad in (
            {"topic": "ab"},
            {"topic": "Irony", "language": "fr"},
            {"topic": "Irony", "style": "chicago"},
            {"topic": "Irony", "target_papers": 2},
            {"topic": "Irony", "sources": ["scholar"]},
            {"topic": "Irony", "from_year": 2020, "to_year": 2010},
        ):
            with self.assertRaises(RunError, msg=bad):
                service.create(bad)
        self.assertEqual(service.list(), [])

    def test_no_model(self):
        from lrg.model import NoModel

        from tests.support import model_store

        with tempfile.TemporaryDirectory() as folder:
            service = self.make_service(models=model_store(Path(folder), choice=None, key=None))
            with self.assertRaises(NoModel) as caught:
                service.create({"topic": "Irony in Austen"})  # nothing chosen
            self.assertEqual(caught.exception.code, "no_model")
            with self.assertRaises(NoModel) as caught:  # chosen, but no key
                service.create(
                    {"topic": "Irony in Austen", "model": {"service": "claude", "model": "c"}}
                )
            self.assertEqual(caught.exception.code, "no_key")
            with self.assertRaises(NoModel):
                service.create(
                    {"topic": "Irony in Austen", "model": {"service": "nope", "model": "m"}}
                )
            self.assertEqual(service.list(), [])

    def test_each_review_uses_its_own_model(self):
        service = self.make_service()
        service.models.save_key("claude", "sk-ant")
        first = service.create({"topic": "Irony in Austen"})
        self.wait(first["id"])
        second = service.create(
            {"topic": "Irony in Austen", "model": {"service": "claude", "model": "claude-x"}}
        )
        self.wait(second["id"])
        self.assertEqual(self.chosen, [CHOICE, {"service": "claude", "model": "claude-x"}])
        self.assertEqual(service.models.current(), {"service": "claude", "model": "claude-x"})
        # Removing the key stops a resume with a clear message.
        service.cancel(second["id"])
        service.models.save_key("claude", "")
        from lrg.model import NoModel

        with self.assertRaises(NoModel):
            service.resume(second["id"])

    def test_cancel(self):
        service = self.make_service()
        run = service.create({"topic": "Irony in Austen"})
        self.wait(run["id"])
        self.assertEqual(service.cancel(run["id"])["status"], "cancelled")
        from lrg.pipeline import RunError

        with self.assertRaises(RunError):
            service.decide(run["id"], "approval_x", True)
        # A cancelled run can be resumed: it is still waiting for the scope.
        service.resume(run["id"])
        self.approve(run["id"])
        self.assertEqual(self.wait(run["id"])["status"], "completed")

    def test_cancel_while_running_stops_before_the_next_model_call(self):
        from lrg.demo import call

        service = self.make_service()
        run = service.create({"topic": "Irony in Austen"})
        summary = self.wait(run["id"])
        state = service._state(run["id"])

        def press_cancel(payload):  # the user presses Cancel while the search stage runs
            state.cancelled = True
            return call("skill.literature-search.invoke")

        self.model.script["search"][0] = press_cancel
        service.decide(run["id"], summary["approvals"][0]["id"], True)
        summary = self.wait(run["id"])
        self.assertEqual(summary["status"], "cancelled")
        self.assertEqual(summary["counts"]["total"], 0)  # stopped before searching

    def test_resume_after_the_app_stopped(self):
        from lrg.pipeline import RunService

        service = self.make_service()
        run = service.create({"topic": "Irony in Austen"})
        self.approve(run["id"])
        self.wait(run["id"])
        # Pretend the app stopped during the last five stages.
        folder = service.folder(run["id"])
        task = json.loads((folder / "task.json").read_text())
        for execution in task["executions"]:
            if execution["node_id"] in ("extract", "organize", "outline", "write", "review"):
                execution["status"] = "failed"
        record = json.loads((folder / "run.json").read_text())
        record["status"] = "running"
        (folder / "run.json").write_text(json.dumps(record))
        restarted = RunService(
            service.data,
            models=service.models,
            model_factory=lambda choice: self.model,
            openalex=service.searches["openalex"],
            arxiv=service.searches["arxiv"],
        )
        self.service = restarted
        self.assertEqual(restarted.summary(run["id"])["status"], "interrupted")
        searches = restarted.summary(run["id"])["counts"]["searches"]
        restarted.resume(run["id"])
        summary = self.wait(run["id"])
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(
            summary["counts"]["searches"], searches
        )  # finished stages are not repeated

    def test_scope_answered_without_submitting_needs_approval(self):
        from lrg.demo import answer, demo_script

        script = demo_script()
        script["scope"] = [answer("A scope written as plain text.")]
        service = self.make_service(script)
        run = service.create({"topic": "Irony in Austen"})
        summary = self.wait(run["id"])
        [approval] = summary["approvals"]
        self.assertFalse(approval["can_revise"])
        self.assertEqual(approval["scope"], {"text": "A scope written as plain text."})
        service.decide(run["id"], approval["id"], False)
        summary = self.wait(run["id"])
        self.assertEqual(summary["status"], "failed")
        from lrg.pipeline import RunError

        with self.assertRaises(RunError):
            service.resume(run["id"])


class StepLimitTests(ServiceCase):
    def test_step_limits_grow_with_the_number_of_papers(self):
        service = self.make_service()
        small = service.workflow({"target_papers": 5})
        large = service.workflow({"target_papers": 80})
        self.assertEqual(
            small.node("scope").react["max_steps"], large.node("scope").react["max_steps"]
        )
        self.assertEqual(large.node("extract").react["max_steps"], 10 + 64)
        self.assertLess(service.call_budget(5)["stages"], service.call_budget(80)["stages"])
        self.assertEqual(service.call_budget(25)["stages"], sum(service.step_limits(25).values()))
        # The run uses the limits of its own request.
        run = service.create({"topic": "Irony in Austen", "target_papers": 80})
        self.wait(run["id"])
        task = service._task(run["id"])
        self.assertEqual(task.executions[0].node_id, "scope")
        graph = service.graph(run["id"])
        self.assertEqual(len(graph["graphs"][0]["nodes"]), 8)


class NoteTests(ServiceCase):
    def test_notes_for_several_papers_at_once(self):
        import tempfile
        from pathlib import Path

        from lrg.tools import RunTools

        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        tools = RunTools(Path(folder.name), {})
        tools.library.add([{"title": "A"}, {"title": "B"}], query="q", source="openalex")
        with self.assertRaises(KeyError):
            tools.note(None, None, {"notes": [{"id": "P1", "summary": "x"}, {"id": "P9"}]})
        self.assertFalse(tools.library.get("P1").get("notes"))  # nothing saved
        reply = tools.note(
            None, None, {"notes": [{"id": "P1", "summary": "x"}, {"id": "P2", "method": "y"}]}
        )
        self.assertEqual(reply, {"saved": ["P1", "P2"], "with_notes": 2})
