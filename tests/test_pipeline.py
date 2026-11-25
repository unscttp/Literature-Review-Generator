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
        summary = self.finish(run["id"])  # approve every graph and the save
        self.assertEqual(summary["status"], "completed", summary.get("error"))
        # Every graph was reviewed: the bundled search graph, the graph the
        # organize stage designed, and saving that graph into its skill.
        self.assertEqual(
            [(a["node"], a["kind"], (a["details"] or {}).get("skill_graph")) for a in self.decided],
            [
                ("search", "graph_creation", "english-literature"),
                ("organize", "graph_creation", None),
                ("organize", "skill_graph_save", None),
            ],
        )

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
        root, child, designed = graph["graphs"]
        self.assertEqual([n["status"] for n in root["nodes"]], ["completed"] * 8)
        self.assertEqual(child["parent"]["node"], "search")
        self.assertEqual(child["title"], "english-literature")
        self.assertFalse(child["designed"])
        self.assertEqual({n["status"] for n in child["nodes"]}, {"completed"})
        self.assertEqual(designed["parent"]["node"], "organize")
        self.assertTrue(designed["designed"])
        self.assertEqual((designed["status"], designed["saved"]), ("completed", "saved"))
        self.assertEqual([n["id"] for n in designed["nodes"]], ["demo-themes", "demo-gaps"])
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
        self.finish(run_id)

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

    def test_a_scope_answer_without_submitting_is_not_accepted(self):
        from lrg.demo import answer, demo_script, submit_scope

        script = demo_script()
        script["scope"] = [answer("A scope written as plain text.")] + script["scope"]
        script["scope"][1] = submit_scope  # after the rejection it submits
        service = self.make_service(script)
        run = service.create({"topic": "Irony in Austen"})
        summary = self.wait(run["id"])
        [approval] = summary["approvals"]
        self.assertEqual(approval["scope"]["title"], "Irony in Jane Austen")
        rejected = [a for a in summary["activity"] if a["kind"] == "react.result_rejected"]
        self.assertIn("not approved", rejected[0]["text"])


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
        tools.library.add(
            [{"title": "A"}, {"title": "B"}, {"title": "C"}], query="q", source="openalex"
        )
        with self.assertRaises(ValueError):  # candidates cannot get notes
            tools.note(None, None, {"notes": [{"id": "P1", "summary": "x"}]})
        tools.decide(
            None,
            None,
            {
                "decisions": [
                    {"id": "P1", "decision": "include"},
                    {"id": "P2", "decision": "include"},
                ]
            },
        )
        with self.assertRaises(KeyError):
            tools.note(None, None, {"notes": [{"id": "P1", "summary": "x"}, {"id": "P9"}]})
        self.assertFalse(tools.library.get("P1").get("notes"))  # nothing saved
        reply = tools.note(
            None, None, {"notes": [{"id": "P1", "summary": "x"}, {"id": "P2", "method": "y"}]}
        )
        self.assertEqual(reply, {"saved": ["P1", "P2"], "with_notes": 2})
        # Themes, outline and citations: included papers only, nothing saved otherwise.
        with self.assertRaises(ValueError):
            tools.tag(None, None, {"assignments": [{"id": "P3", "themes": ["T"]}]})
        with self.assertRaises(ValueError):
            tools.set_outline(
                None,
                None,
                {
                    "sections": [
                        {"id": "a", "title": "A", "purpose": "x", "papers": ["P1", "P3"]},
                        {"id": "b", "title": "B", "purpose": "y"},
                    ]
                },
            )
        self.assertEqual(tools.outline(), [])
        with self.assertRaises(ValueError):
            tools.write_section(
                None, None, {"section_id": "a", "title": "A", "content": "x [P1, P3]"}
            )
        self.assertEqual(tools.sections.all(), [])
        # The rest of the candidates in one call, once something is included.
        reply = tools.exclude_remaining(None, None, {"reason": "E6: lower priority"})
        self.assertEqual((reply["excluded"], reply["counts"]["candidate"]), (1, 0))
        self.assertEqual(tools.library.get("P3")["reason"], "E6: lower priority")


class GateTests(ServiceCase):
    """A stage that did not do its work cannot hand on a result (the 0-included run)."""

    def approve_scope(self, service, run_id):
        return self.finish(run_id)

    def test_screening_that_decides_nothing_stops_the_run(self):
        from lrg.demo import answer, demo_script

        script = demo_script()
        script["screen"] = [answer("Screened: 35 papers included.")]  # but nothing recorded
        service = self.make_service(script)
        run = service.create({"topic": "Irony in Austen"})
        summary = self.approve_scope(service, run["id"])
        self.assertEqual(summary["status"], "failed")
        self.assertIn("still candidates", summary["error"])
        self.assertEqual(summary["counts"]["included"], 0)
        statuses = {n["id"]: n["status"] for n in service.graph(run["id"])["graphs"][0]["nodes"]}
        self.assertEqual(statuses["screen"], "failed")
        self.assertEqual(statuses["extract"], "pending")  # later stages never started
        self.assertEqual(summary["sections"], [])
        rejected = [a for a in summary["activity"] if a["kind"] == "react.result_rejected"]
        self.assertTrue(rejected)

    def test_a_rejected_stage_finishes_its_work_and_goes_on(self):
        from lrg.demo import answer, call, demo_script

        script = demo_script()
        decide = script["screen"][1]
        script["screen"] = [
            answer("Done screening."),  # too early: rejected with what is missing
            call("library.decide", decisions=[{"id": "P1", "decision": "include", "reason": "ok"}]),
            answer("Done."),  # P2-P4 still candidates: rejected again
            decide,
            answer("2 included, 2 excluded."),
        ]
        service = self.make_service(script)
        run = service.create({"topic": "Irony in Austen"})
        summary = self.approve_scope(service, run["id"])
        self.assertEqual(summary["status"], "completed", summary.get("error"))
        rejected = [a["text"] for a in summary["activity"] if a["kind"] == "react.result_rejected"]
        self.assertEqual(len(rejected), 2)
        self.assertIn("4 of 4 papers are still candidates", rejected[0])
        self.assertIn("3 of 4 papers are still candidates (P2, P3, P4)", rejected[1])
        self.assertTrue(service.report(run["id"])["check"]["complete"])

    def test_the_review_stage_cannot_finish_with_blocking_issues(self):
        from lrg.demo import answer, call, demo_script

        script = demo_script()
        script["review"] = [call("review.check"), answer("Finished.")]  # no abstract written
        service = self.make_service(script)
        run = service.create({"topic": "Irony in Austen"})
        summary = self.approve_scope(service, run["id"])
        self.assertEqual(summary["status"], "failed")
        self.assertIn("missing_abstract", summary["error"])
        self.assertFalse(service.report(run["id"])["check"]["complete"])


class DesignedGraphTests(ServiceCase):
    """A stage designs a graph, the user reviews it, it runs, is saved and reused."""

    def test_saved_graph_is_reused_by_the_next_review(self):
        from lrg.demo import DEMO_GRAPH_TITLE

        service = self.make_service()
        first = service.create({"topic": "Irony in Austen"})
        self.assertEqual(self.finish(first["id"])["status"], "completed")
        skills = {s["name"]: s for s in service.workflow_view()["skills"]}
        graphs = skills["review-organization"]["graphs"]
        saved = next(g for g in graphs if g["title"] == DEMO_GRAPH_TITLE)
        self.assertFalse(saved["bundled"])
        self.assertEqual(saved["runs"], 1)  # the run it was saved from
        self.assertTrue(next(g for g in graphs if g["id"] == "fast-moving-cs")["bundled"])

        self.decided = []
        second = service.create({"topic": "Irony in Austen"})
        self.assertEqual(self.finish(second["id"])["status"], "completed")
        organize = [a for a in self.decided if a["node"] == "organize"]
        self.assertEqual(len(organize), 1)  # run the saved graph; nothing new to save
        self.assertEqual(organize[0]["details"]["skill_graph"], saved["id"])
        self.assertEqual(organize[0]["skill_graph_title"], DEMO_GRAPH_TITLE)
        reused = service.graph(second["id"])["graphs"][2]
        self.assertEqual(
            (reused["designed"], reused["skill_graph_title"]), (False, DEMO_GRAPH_TITLE)
        )
        skills = {s["name"]: s for s in service.workflow_view()["skills"]}
        again = next(g for g in skills["review-organization"]["graphs"] if g["id"] == saved["id"])
        self.assertEqual(again["runs"], 2)

        # Saved graphs can be removed; the bundled samples cannot.
        from lrg.pipeline import RunError

        with self.assertRaises(RunError):
            service.delete_skill_graph("review-organization", "fast-moving-cs")
        service.delete_skill_graph("review-organization", saved["id"])
        skills = {s["name"]: s for s in service.workflow_view()["skills"]}
        self.assertEqual(
            [g["id"] for g in skills["review-organization"]["graphs"]], ["fast-moving-cs"]
        )

    def test_a_rejected_graph_lets_the_stage_go_on(self):
        service = self.make_service()
        run = service.create({"topic": "Irony in Austen"})

        def decide(approval):
            if approval["kind"] == "graph_creation" and approval["node"] == "organize":
                return False, "Assign the themes yourself."
            return True, ""

        summary = self.finish(run["id"], decide)
        self.assertEqual(summary["status"], "completed", summary.get("error"))
        self.assertNotIn("skill_graph_save", [a["kind"] for a in self.decided])
        designed = service.graph(run["id"])["graphs"][2]
        self.assertEqual(designed["status"], "rejected")
        self.assertTrue(all(n["status"] == "pending" for n in designed["nodes"]))  # never ran
        kinds = [a["kind"] for a in summary["activity"]]
        self.assertIn("graph.rejected", kinds)
        organize_calls = [n for n in self.model.tools if n[0] == "organize"]
        self.assertTrue(organize_calls)

    def test_designing_graphs_can_be_switched_off(self):
        service = self.make_service()
        run = service.create({"topic": "Irony in Austen", "design_graphs": False})
        summary = self.finish(run["id"])
        self.assertEqual(summary["status"], "completed", summary.get("error"))
        self.assertNotIn("organize", [a["node"] for a in self.decided])
        offered = {tool for node, tools in self.model.tools if node == "organize" for tool in tools}
        self.assertNotIn("graph.create", offered)
        self.assertIn("skill.review-organization.run_graph", offered)  # saved graphs still run
        from lrg.pipeline import RunError

        with self.assertRaises(RunError):
            service.create({"topic": "Irony in Austen", "design_graphs": "yes"})
