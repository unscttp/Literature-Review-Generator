"""Review runs: one DGS task of the eight-stage workflow each.

``RunService.create`` stores the request in a new run folder
(``data/runs/<id>/``) and runs the workflow in a background thread. Each run
gets its own DGS engine and tool module bound to its folder. The task is
saved after every stage and before every model call, so the web interface
can show it and an interrupted run can continue.

The run pauses when the scope is submitted for approval (``scope.submit``).
``decide`` records the user's decision and continues the run. ``cancel``
stops it before its next model call. ``resume`` continues a run that failed
or was interrupted (the app was closed): DGS retries the stage, answering the
actions that already completed from its journal instead of repeating them.
"""

from __future__ import annotations

import copy
import json
import math
import re
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from workflow_core import (
    AllowanceRegistry,
    Task,
    WorkflowDefinition,
    WorkflowEngine,
    pending_human_checks,
    resolve_human_check,
)

from . import ROOT
from .gates import register_gates
from .graph_view import task_graph
from .library import Library, write_json
from .live import LiveTasks
from .model import ModelStore, local_settings, with_rules
from .references import STYLES
from .report import build, check
from .skills import install_skill
from .sources import arxiv_search, openalex_search
from .tools import SKILLS, RunTools

GRAPH_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")

CONFIG = ROOT / "config"
NODE_TYPE = "stage"
LANGUAGES = ("en", "zh-CN")
REVIEW_TYPES = ("narrative", "scoping", "systematic")
SOURCES = ("openalex", "arxiv")
ACTIVE = ("queued", "running")
# The sentences of a stage instruction about designing a graph (see config/workflow.json).
DESIGN_ADVICE = re.compile(
    r" If none of the skill's saved graphs fits, and the work splits.*?continue without it\."
)
EVENT_KINDS = (
    "tool.requested",
    "tool.completed",
    "tool.failed",
    "llm.retry",
    "approval.requested",
    "approval.resolved",
    "graph.requested",
    "graph.completed",
    "graph.failed",
    "skill.invoke.opened",
    "node.failed",
    "react.result_rejected",
    "graph.created",
    "graph.rejected",
    "skill.graph.saved",
    "skill.graph.save_declined",
)


class RunError(ValueError):
    """A request the service refuses (bad input, wrong state)."""


def load_settings(path: Path | None = None) -> dict:
    return json.loads((path or CONFIG / "settings.json").read_text("utf-8"))


def validate_request(raw: dict, defaults: dict) -> dict:
    if not isinstance(raw, dict):
        raise RunError("The request must be a JSON object.")
    topic = str(raw.get("topic") or "").strip()
    if not 3 <= len(topic) <= 500:
        raise RunError("topic: 3 to 500 characters.")
    request = {
        "topic": topic,
        "language": raw.get("language") or defaults["language"],
        "style": raw.get("style") or defaults["style"],
        "review_type": raw.get("review_type") or defaults["review_type"],
        "target_papers": raw.get("target_papers") or defaults["target_papers"],
        "sources": raw.get("sources") or list(defaults["sources"]),
        "notes": str(raw.get("notes") or "").strip()[:2000],
        # Whether stages may design graphs of their own (graph.create).
        "design_graphs": raw.get("design_graphs", defaults.get("design_graphs", True)),
    }
    if type(request["design_graphs"]) is not bool:
        raise RunError("design_graphs must be true or false.")
    if request["language"] not in LANGUAGES:
        raise RunError(f"language must be one of {LANGUAGES}.")
    if request["style"] not in STYLES:
        raise RunError(f"style must be one of {STYLES}.")
    if request["review_type"] not in REVIEW_TYPES:
        raise RunError(f"review_type must be one of {REVIEW_TYPES}.")
    if type(request["target_papers"]) is not int or not 5 <= request["target_papers"] <= 80:
        raise RunError("target_papers must be a whole number from 5 to 80.")
    if (
        not isinstance(request["sources"], list)
        or not request["sources"]
        or not set(request["sources"]) <= set(SOURCES)
    ):
        raise RunError(f"sources: one or more of {SOURCES}.")
    for key in ("from_year", "to_year"):
        value = raw.get(key)
        if value in (None, ""):
            continue
        if type(value) is not int or not 1500 <= value <= 2100:
            raise RunError(f"{key} must be a year.")
        request[key] = value
    if (
        request.get("from_year")
        and request.get("to_year")
        and request["from_year"] > request["to_year"]
    ):
        raise RunError("from_year must not be after to_year.")
    return request


@dataclass
class RunState:
    """What the service keeps in memory for a run that is running."""

    thread: threading.Thread | None = None
    live: LiveTasks = field(default_factory=LiveTasks)
    task: Task | None = None
    cancelled: bool = False


class RunService:
    def __init__(
        self,
        data_dir: Path | None = None,
        *,
        settings: dict | None = None,
        models: ModelStore | None = None,
        model_factory: Callable[[dict], Callable] | None = None,
        demo_label: str | None = None,
        openalex=openalex_search,
        arxiv=arxiv_search,
    ) -> None:
        self.settings = settings or load_settings()
        self.data = Path(data_dir or ROOT / "data")
        self.runs_dir = self.data / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.skills_dir = self.data / "skills"
        for name in SKILLS:
            install_skill(ROOT / "skills" / name, self.skills_dir / name)
        # The AI services, keys and saved choice. Each review records its own choice.
        self.models = models or ModelStore()
        self.model_factory = model_factory or self.models.adapter
        # Demo mode: a scripted model; reviews need no choice and no key.
        self.demo_label = demo_label
        self.searches = {"openalex": openalex, "arxiv": arxiv}
        self.allowances = AllowanceRegistry()
        for path in sorted((CONFIG / "allowances").glob("*.json")):
            self.allowances.load(path)
        self.workflow_document = json.loads((CONFIG / "workflow.json").read_text("utf-8"))
        self.workflow().assert_valid()
        self.rules = (CONFIG / "rules.md").read_text("utf-8").strip()
        self._states: dict[str, RunState] = {}
        self._guard = threading.Lock()
        # Runs that were running when the app stopped can be resumed.
        for run in self.list():
            if run["status"] in ACTIVE:
                self._update(
                    run["id"], status="interrupted", error="The app stopped during the run."
                )

    # -- files -------------------------------------------------------------------

    def step_limits(self, target_papers: int) -> dict[str, int]:
        """Each stage's step limit for a review of ``target_papers`` papers: the
        ``max_steps`` in config/workflow.json plus ``steps_per_paper`` per paper."""
        per_paper = self.settings.get("steps_per_paper", {})
        return {
            node["id"]: node["react"]["max_steps"]
            + math.ceil(per_paper.get(node["id"], 0) * target_papers)
            for node in self.workflow_document["nodes"]
        }

    def call_budget(self, target_papers: int) -> dict:
        """The most model calls the stages may make, for the new-review form."""
        limits = self.step_limits(target_papers)
        return {
            "stages": sum(limits.values()),
            "per_stage": limits,
            "skill_graph": self.settings["engine"].get("graph_max_steps", 100),
        }

    def workflow(self, request: dict | None = None) -> WorkflowDefinition:
        """The workflow, with the step limits for ``request``'s number of papers."""
        document = copy.deepcopy(self.workflow_document)
        if request is not None:
            limits = self.step_limits(request["target_papers"])
            for node in document["nodes"]:
                node["react"]["max_steps"] = limits[node["id"]]
                if not request.get("design_graphs", True) and node.get("allow_create_graph"):
                    # No graph.create for this review: drop the flag and the advice.
                    node["allow_create_graph"] = False
                    node["config"]["instruction"] = DESIGN_ADVICE.sub(
                        "", node["config"]["instruction"]
                    )
        return WorkflowDefinition.from_dict(document)

    def folder(self, run_id: str) -> Path:
        if not isinstance(run_id, str) or not run_id.replace("-", "").isalnum():
            raise KeyError(run_id)
        folder = self.runs_dir / run_id
        if not (folder / "run.json").is_file():
            raise KeyError(run_id)
        return folder

    def record(self, run_id: str) -> dict:
        return json.loads((self.folder(run_id) / "run.json").read_text("utf-8"))

    def _update(self, run_id: str, **changes) -> dict:
        with self._guard:
            record = self.record(run_id)
            record.update(changes, updated=time.time())
            write_json(self.folder(run_id) / "run.json", record)
            return record

    def _state(self, run_id: str) -> RunState:
        with self._guard:
            return self._states.setdefault(run_id, RunState())

    def _task(self, run_id: str) -> Task | None:
        state = self._states.get(run_id)
        if state is not None and state.task is not None:
            return state.task
        path = self.folder(run_id) / "task.json"
        return Task.load(path) if path.is_file() else None

    def _save_task(self, run_id: str, task: Task) -> None:
        write_json(self.folder(run_id) / "task.json", task.to_dict())

    # -- the engine ----------------------------------------------------------------

    def model_label(self, choice: dict | None) -> str:
        if self.demo_label:
            return self.demo_label
        return self.models.label(choice) if choice else "?"

    def _choice(self, record: dict) -> dict | None:
        """The model a review uses (reviews from before 1.1 use the saved default)."""
        return record.get("model_choice") or self.models.current()

    def _engine(
        self, run_id: str, tools: RunTools, state: RunState, root: Task, choice: dict | None
    ) -> WorkflowEngine:
        engine = WorkflowEngine(self.allowances, tools=tools.module(self.skills_dir))
        engine.setting_overrides = dict(self.settings["engine"])
        # Recorded with every run of a skill graph: the graph's history then says
        # which model it last worked with.
        engine.host_environment = {"model": self.model_label(choice)}

        def observe(task, execution):
            state.live.observe(task, execution)
            self._save_task(run_id, root)

        engine.add_run_observer(observe)

        def saved_model(adapter):
            def call(messages):
                self._save_task(run_id, root)  # every completed action is on disk
                return adapter(messages)

            return call

        model = with_rules(self.model_factory(choice), self.rules, lambda: state.cancelled)
        engine.register_llm(NODE_TYPE, saved_model(model), memory_writer=False)

        # Each stage's answer counts only once its work is really done (lrg/gates.py).
        register_gates(engine, tools)
        return engine

    def _tools(self, run_id: str, request: dict) -> RunTools:
        return RunTools(
            self.folder(run_id),
            request,
            openalex_key=lambda: local_settings().get("openalex_api_key"),
            openalex=self.searches["openalex"],
            arxiv=self.searches["arxiv"],
        )

    def _drive(self, run_id: str, *, retry: bool = False) -> None:
        state = self._state(run_id)
        record = self.record(run_id)
        workflow = self.workflow(record["request"])
        try:
            task = self._task(run_id) or Task.create(workflow, {"request": record["request"]})
            task.metadata["run_id"] = run_id
            state.task = task
            tools = self._tools(run_id, record["request"])
            engine = self._engine(run_id, tools, state, task, self._choice(record))
            if retry:
                for execution in task.executions:
                    if execution.status == "running":  # the app stopped mid-stage
                        execution.status, execution.error = "failed", "interrupted"
                    if execution.status == "failed":
                        engine.retry_execution(task, execution, replay=True)
            self._update(run_id, status="running", task_id=task.id, error=None)
            engine.task_pool.add(task)
            while ready := engine.task_pool.ready():
                for ready_task, execution in ready:
                    engine.run_execution(workflow, ready_task, execution)
                    self._save_task(run_id, task)
            self._finish(run_id, task, tools, state)
        except Exception as exc:  # never leave a run marked as running
            if state.task is not None:
                self._save_task(run_id, state.task)
            self._update(run_id, status="failed", error=f"{type(exc).__name__}: {exc}")
        finally:
            state.live.clear()
            state.task = None
            state.thread = None

    def _finish(self, run_id: str, task: Task, tools: RunTools, state: RunState) -> None:
        self._save_task(run_id, task)
        scope = tools.scope() or {}
        title = scope.get("title") or self.record(run_id)["request"]["topic"]
        if pending_human_checks(task):
            self._update(run_id, status="waiting", title=title)
        elif task.status == "completed":
            self._write_report(run_id)
            self._update(run_id, status="completed", title=title, finished=time.time())
        elif state.cancelled:
            self._update(run_id, status="cancelled", title=title)
        else:
            errors = [e.error for e in task.executions if e.status == "failed" and e.error]
            self._update(
                run_id,
                status="failed",
                title=title,
                error=errors[-1] if errors else "The run failed.",
            )

    def _start(self, run_id: str, *, retry: bool = False) -> None:
        state = self._state(run_id)
        with self._guard:
            if state.thread is not None:
                raise RunError("The run is already running.")
            state.cancelled = False
            state.thread = threading.Thread(
                target=self._drive, args=(run_id,), kwargs={"retry": retry}, daemon=True
            )
        self._update(run_id, status="running", error=None)
        state.thread.start()

    # -- actions ---------------------------------------------------------------------

    def create(self, raw: dict) -> dict:
        request = validate_request(raw, self.settings["defaults"])
        if self.demo_label:
            choice = {"service": "demo", "model": "demo"}
        else:
            # Fails now, not in the thread, if the model is unknown or has no key.
            choice = self.models.clean(raw.get("model") or self.models.current())
            self.models.save_choice(choice)  # the default for the next review
        run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
        folder = self.runs_dir / run_id
        folder.mkdir(parents=True)
        now = time.time()
        write_json(
            folder / "run.json",
            {
                "id": run_id,
                "title": request["topic"],
                "request": request,
                "status": "queued",
                "model": self.model_label(choice),
                "model_choice": choice,
                "created": now,
                "updated": now,
                "task_id": None,
                "error": None,
            },
        )
        self._start(run_id)
        return self.summary(run_id)

    def decide(self, run_id: str, request_id: str, approved: bool, comment: str = "") -> dict:
        record = self.record(run_id)
        if record["status"] != "waiting":
            raise RunError("The run is not waiting for a decision.")
        task = self._task(run_id)
        try:
            resolve_human_check(
                task, request_id, bool(approved), reviewer="local-user", comment=comment[:2000]
            )
        except (KeyError, ValueError) as exc:
            raise RunError(str(exc)) from None
        self._save_task(run_id, task)
        self._start(run_id)
        return self.summary(run_id)

    def cancel(self, run_id: str) -> dict:
        record = self.record(run_id)
        state = self._state(run_id)
        if record["status"] in ACTIVE and state.thread is not None:
            state.cancelled = True  # the thread stops before its next model call
        elif record["status"] in ("waiting", "interrupted", "failed"):
            self._update(run_id, status="cancelled")
        else:
            raise RunError("The run cannot be cancelled now.")
        return self.summary(run_id)

    def resume(self, run_id: str) -> dict:
        record = self.record(run_id)
        if record["status"] not in ("interrupted", "failed", "cancelled"):
            raise RunError("Only interrupted, failed or cancelled runs can be resumed.")
        if not self.demo_label:
            self.models.resolve(self._choice(record))  # the key may have been removed
        task = self._task(run_id)
        if task is not None and any(
            request["status"] == "rejected" and not request["details"].get("on_reject")
            for execution in task.executions
            for request in execution.human_checks
        ):
            raise RunError("The scope was rejected; start a new review.")
        self._start(run_id, retry=task is not None)
        return self.summary(run_id)

    def delete(self, run_id: str) -> None:
        if self.record(run_id)["status"] in ACTIVE:
            raise RunError("Cancel the run before deleting it.")
        folder = self.folder(run_id)
        for path in sorted(folder.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        folder.rmdir()
        self._states.pop(run_id, None)

    # -- views -------------------------------------------------------------------------

    def list(self) -> list[dict]:
        runs = []
        for path in self.runs_dir.glob("*/run.json"):
            try:
                record = json.loads(path.read_text("utf-8"))
            except (OSError, ValueError):
                continue
            runs.append(
                {key: record.get(key) for key in ("id", "title", "status", "created", "updated")}
                | {"language": record["request"]["language"]}
            )
        return sorted(runs, key=lambda run: run["created"], reverse=True)

    def summary(self, run_id: str) -> dict:
        record = self.record(run_id)
        folder = self.folder(run_id)
        task = self._task(run_id)
        tools = RunTools(folder, record["request"])
        approvals = []
        for request in pending_human_checks(task) if task else []:
            details = request["details"]
            approvals.append(
                {
                    "id": request["id"],
                    "kind": details.get("kind", "custom"),
                    "node": request.get("node_id"),
                    "scope": details.get("scope"),
                    "can_revise": details.get("on_reject") == "continue",
                    "details": None if details.get("kind") == "scope_review" else details,
                    "skill_graph_title": self._skill_graph_title(details),
                }
            )
        return {
            **record,
            "scope": tools.scope(),
            "stages": (task.data.get("stages") if task else None) or {},
            "approvals": approvals,
            "counts": tools.library.counts(),
            "sections": tools.sections.summary(),
            "stats": run_stats(task) if task else {},
            "activity": activity(task) if task else [],
        }

    def graph(self, run_id: str) -> dict:
        state = self._states.get(run_id)
        live = state.live if state else LiveTasks()
        task = self._task(run_id)
        view = task_graph(
            self.workflow(self.record(run_id)["request"]),
            task,
            live,
            running=state is not None and state.thread is not None,
        )
        for graph in view["graphs"]:
            if graph.get("parent"):
                graph["skill_graph_title"] = self._skill_graph_title(graph)
        return view

    def _skill_graph_title(self, details: dict) -> str | None:
        """The title (first scenario line) of the saved graph a request or view names."""
        skill = details.get("skill")
        name = skill.get("name") if isinstance(skill, dict) else skill
        graph_id = details.get("skill_graph")
        if not name or not graph_id or name not in SKILLS:
            return None
        from workflow_core import list_skill_graphs

        for summary in list_skill_graphs(self.skills_dir / name):
            if summary["id"] == graph_id:
                return summary.get("title") or graph_id
        return graph_id

    def delete_skill_graph(self, skill: str, graph_id: str) -> None:
        """Remove a graph saved from a review (the bundled sample graphs stay)."""
        if skill not in SKILLS or not GRAPH_ID.fullmatch(graph_id or ""):
            raise KeyError(graph_id)
        if (ROOT / "skills" / skill / "graphs" / f"{graph_id}.json").exists():
            raise RunError("The sample graphs that come with the app cannot be removed.")
        folder = self.skills_dir / skill / "graphs"
        files = [folder / f"{graph_id}{suffix}" for suffix in (".json", ".md", ".meta.json")]
        if not files[0].is_file():
            raise KeyError(graph_id)
        for path in files:
            path.unlink(missing_ok=True)

    def library(self, run_id: str) -> dict:
        library = Library(self.folder(run_id) / "library.json")
        return {"counts": library.counts(), **library.snapshot()}

    def report(self, run_id: str) -> dict:
        record = self.record(run_id)
        folder = self.folder(run_id)
        tools = RunTools(folder, record["request"])
        result = build(
            tools.library,
            tools.sections,
            style=record["request"]["style"],
            language=record["request"]["language"],
            title=(tools.scope() or {}).get("title") or record["request"]["topic"],
        )
        result["check"] = check(tools.library, tools.sections, [s["id"] for s in tools.outline()])
        return result

    def _write_report(self, run_id: str) -> None:
        report = self.report(run_id)
        folder = self.folder(run_id)
        (folder / "report.md").write_text(report["markdown"], "utf-8")
        (folder / "references.bib").write_text(report["bibtex"], "utf-8")

    def workflow_view(self) -> dict:
        """The workflow and the skills' sample graphs, for the viewer without a run."""
        return {
            "workflow": task_graph(self.workflow(), None, LiveTasks()),
            "skills": skill_graphs(self.skills_dir, ROOT / "skills"),
        }


def skill_graphs(skills_dir: Path, bundled_dir: Path) -> list[dict]:
    """Each skill's graphs: the bundled samples and those saved from reviews."""
    from workflow_core import list_skill_graphs, load_skill_graph
    from workflow_skill_graph_meta import read_meta

    skills = []
    for name in SKILLS:
        root = Path(skills_dir) / name
        graphs = []
        for summary in list_skill_graphs(root):
            if summary.get("invalid"):
                continue
            saved = load_skill_graph(root, summary["id"])
            meta = read_meta(root, summary["id"]) or {}
            graphs.append(
                {
                    "id": saved["id"],
                    "title": summary["title"],
                    "bundled": (bundled_dir / name / "graphs" / f"{saved['id']}.json").exists(),
                    "saved_at": (meta.get("saved") or {}).get("at") or summary.get("saved_at"),
                    "runs": (meta.get("runs") or {}).get("total", 0),
                    "explanation": saved["explanation"],
                    "usage_scenario": saved["usage_scenario"],
                    "start": saved["start"],
                    "nodes": [
                        {
                            "id": n["id"],
                            "name": n.get("name") or n["id"],
                            "allowance": n.get("allowance"),
                            "instruction": (n.get("config") or {}).get("instruction"),
                            "status": "pending",
                        }
                        for n in saved["graph"]["nodes"]
                    ],
                    "edges": [{"from": e["from"], "to": e["to"]} for e in saved["graph"]["edges"]],
                }
            )
        skills.append({"name": name, "graphs": graphs})
    return skills


def run_stats(task: Task) -> dict:
    decisions = [e["details"] for e in task.events if e["type"] == "llm.completed"]
    return {
        "decisions": len(decisions),
        "tokens": sum(d.get("tokens") or 0 for d in decisions),
        "tool_calls": sum(e["type"] in ("tool.completed", "tool.failed") for e in task.events),
        "retries": sum(e["type"].endswith(".retry") for e in task.events),
    }


def _short(value, limit: int = 160) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def activity(task: Task, limit: int = 120) -> list[dict]:
    """The latest tool calls and other notable events, newest last."""
    nodes = {execution.id: execution.node_id for execution in task.executions}
    entries = []
    for event in list(task.events):
        kind = event["type"]
        if kind not in EVENT_KINDS:
            continue
        details = event["details"]
        entry = {
            "at": event["timestamp"],
            "kind": kind,
            "node": nodes.get(event.get("execution_id")),
        }
        if kind == "tool.requested":
            entry["tool"] = str(details.get("action", "")).removeprefix("tool:")
            entry["text"] = _short(details.get("arguments") or {})
        elif kind == "tool.failed":
            entry["text"] = _short(f"{details.get('error_type')}: {details.get('error')}")
        elif kind == "skill.invoke.opened":
            entry["tool"] = details.get("skill")
        elif kind in ("graph.failed", "node.failed"):
            entry["text"] = _short(details.get("error") or "")
        elif kind == "graph.rejected":
            entry["text"] = _short(details.get("comment") or "")
        elif kind in ("skill.graph.saved", "skill.graph.save_declined"):
            entry["tool"] = details.get("name")
        elif kind == "react.result_rejected":
            entry["text"] = _short(details.get("problem") or "", 300)
        entries.append(entry)
    return entries[-limit:]
