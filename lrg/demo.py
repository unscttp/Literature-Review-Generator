"""A scripted run for ``python run.py --demo``: the app without an AI model.

The demo model is a fixed script, not an AI: it walks through all eight
stages with the real tools, the real scope approval and a real skill graph
(``english-literature``), on a few made-up records from ``DEMO_RECORDS``
instead of OpenAlex and arXiv. It shows how the app works and checks the
installation without an API key or a network. The tests use it too.

Every demo record is marked as an example (authors "Example", venue "Demo
...") so it cannot be mistaken for real literature.
"""

from __future__ import annotations

import json

from workflow_core import NodeResult, ReActAction

MODEL_LABEL = "demo script (no AI)"

DEMO_RECORDS = {
    "austen irony": [
        {
            "title": "Irony and Narrative Voice in Pride and Prejudice (demo record)",
            "authors": ["Ann Example", "Ben Example"],
            "year": 2015,
            "venue": "Demo Journal of Literary Studies",
            "type": "journal-article",
            "volume": "70",
            "issue": "2",
            "pages": "150-178",
            "abstract": "Reads Austen's irony through free indirect discourse.",
            "cited_by": 40,
        },
        {
            "title": "The Ironic Imagination (demo record)",
            "authors": ["Cleo Example"],
            "year": 2009,
            "venue": "Demo University Press",
            "type": "book",
            "publisher": "Demo University Press",
            "abstract": "",
            "cited_by": 120,
        },
    ],
    "default": [
        {
            "title": "Irony in Chemistry Teaching (demo record)",
            "authors": ["Dan Example"],
            "year": 2020,
            "venue": "Demo Journal of Chemistry",
            "type": "journal-article",
            "abstract": "Off topic.",
            "cited_by": 2,
        },
    ],
}


def demo_openalex(query, **options):
    records = DEMO_RECORDS.get(query.lower(), DEMO_RECORDS["default"])
    return [dict(record, source="openalex") for record in records]


def demo_arxiv(query, **options):
    return [
        {
            "title": "Detecting Irony in Novels (demo record)",
            "authors": ["Eve Example"],
            "year": 2023,
            "venue": "arXiv",
            "type": "preprint",
            "arxiv_id": "0000.00001",
            "abstract": "A corpus method.",
            "source": "arxiv",
        }
    ]


def payload_of(messages):
    return json.loads(messages[-1]["content"])


def last(payload):
    return payload["history"][-1]["observation"] if payload.get("history") else None


def answer(text):
    return NodeResult(values={"answer": text})


def call(name, **arguments):
    return ReActAction(f"tool:{name}", arguments)


def invoke_id(payload):
    for entry in payload["history"]:
        observation = entry.get("observation") or {}
        if isinstance(observation, dict) and "invoke_id" in observation:
            return observation["invoke_id"]
    raise LookupError("no open skill in the history")


def chinese(payload) -> bool:
    request = (payload.get("inputs") or {}).get("request") or {}
    return request.get("language") == "zh-CN"


SCOPE = {
    "title": "Irony in Jane Austen",
    "research_questions": ["How does Austen's narration create irony?"],
    "inclusion_criteria": ["Criticism of Austen's novels"],
    "search_queries": ["austen irony"],
}
SCOPE_ZH = {
    "title": "简·奥斯丁小说中的反讽",
    "research_questions": ["奥斯丁的叙述如何制造反讽？"],
    "inclusion_criteria": ["关于奥斯丁小说的文学批评"],
    "search_queries": ["austen irony"],
}
TEXT = {
    "introduction": (
        "Introduction",
        "Irony is central to Austen's narration, as criticism has argued in many forms and "
        "with many emphases over the last decades. This demo review shows how the stages "
        "work together: a scope you approve, searches that fill a library, screening, notes, "
        "themes, an outline and the text. Its sources are example records [P2].",
        "引言",
        "反讽是奥斯丁叙述艺术的核心，这一点在过去几十年的批评中以多种方式得到论述。本示例综述展示各阶段如何协同工作，"
        "所用文献均为示例记录 [P2]。",
    ),
    "narrative-voice": (
        "Narrative voice",
        "Free indirect discourse carries much of the irony [P1], a reading that extends the "
        "earlier account of an ironic imagination [P2]. Both treat irony as a matter of voice "
        "rather than of plot, and both locate it in the narrator's closeness to the characters.",
        "叙述声音",
        "自由间接引语（free indirect discourse）承载了大部分反讽 [P1]，这一解读延续了此前关于“反讽想象”的论述 [P2]。"
        "两者都把反讽视为声音而非情节的问题，并将其归于叙述者与人物之间的亲近关系。",
    ),
    "abstract": (
        "Abstract",
        "This demo review examines irony in Austen's novels across two strands of criticism "
        "and finds that narrative voice is the main mechanism. It was produced by the demo "
        "script on example records and shows the eight stages of the workflow.",
        "摘要",
        "本示例综述考察奥斯丁小说中的反讽，梳理了两条批评脉络，认为叙述声音是反讽的主要机制。"
        "本文由演示脚本基于示例记录生成，用于展示工作流的八个阶段。",
    ),
}


def write(section_id):
    def step(payload):
        title, text, title_zh, text_zh = TEXT[section_id]
        if chinese(payload):
            title, text = title_zh, text_zh
        return call("review.write_section", section_id=section_id, title=title, content=text)

    return step


def submit_scope(payload):
    scope = SCOPE_ZH if chinese(payload) else SCOPE
    previous = last(payload)
    if previous and previous.get("approved") is False:  # sent back with a comment
        return call("scope.submit", **scope, notes=f"Revised: {previous['feedback']}")
    return call("scope.submit", **scope)


def demo_script():
    """Steps per node id, chosen by how many actions the node has taken."""
    return {
        "scope": [
            submit_scope,
            lambda p: submit_scope(p) if not last(p)["approved"] else answer("Scope approved."),
            lambda p: submit_scope(p) if not last(p)["approved"] else answer("Scope approved."),
            answer("Scope approved."),
        ],
        "search": [
            call("skill.literature-search.invoke"),
            lambda p: call(
                "skill.literature-search.run_graph",
                invoke_id=invoke_id(p),
                graph_id="english-literature",
            ),
            call("lit.search_arxiv", query="irony detection novels"),
            lambda p: call("skill.literature-search.finish", invoke_id=invoke_id(p)),
            answer("Searched OpenAlex (with the english-literature graph) and arXiv."),
        ],
        # the nodes of the english-literature graph
        "plan": [answer("(a) austen irony")],
        "criticism": [call("lit.search_openalex", query="austen irony"), answer("2 found")],
        "context": [call("lit.search_openalex", query="regency satire"), answer("1 found")],
        "coverage": [call("library.list"), answer("No gaps.")],
        "screen": [
            call("library.list", status="candidate", detail="abstract"),
            call(
                "library.decide",
                decisions=[
                    {"id": "P1", "decision": "include", "reason": "on topic"},
                    {"id": "P2", "decision": "include", "reason": "central book"},
                    {"id": "P3", "decision": "exclude", "reason": "E1: chemistry"},
                    {"id": "P4", "decision": "exclude", "reason": "E3: computational"},
                ],
            ),
            answer("2 included, 2 excluded."),
        ],
        "extract": [
            call("library.get", ids=["P1", "P2"]),
            call(
                "library.note",
                notes=[
                    {
                        "id": "P1",
                        "summary": "Irony via free indirect discourse.",
                        "method": "close reading",
                    },
                    {"id": "P2", "summary": "A book on irony.", "method": "not reported"},
                ],
            ),
            answer("Notes for 2 papers."),
        ],
        "organize": [
            call(
                "library.tag",
                assignments=[
                    {"id": "P1", "themes": ["Narrative voice"]},
                    {"id": "P2", "themes": ["Narrative voice"]},
                ],
            ),
            answer("One theme: narrative voice [P1, P2]."),
        ],
        "outline": [
            call(
                "review.set_outline",
                sections=[
                    {"id": "introduction", "title": "Introduction", "purpose": "aims"},
                    {
                        "id": "narrative-voice",
                        "title": "Narrative voice",
                        "purpose": "theme",
                        "papers": ["P1", "P2"],
                    },
                ],
            ),
            answer("Outline saved."),
        ],
        "write": [write("introduction"), write("narrative-voice"), answer("Two sections written.")],
        "review": [call("review.check"), write("abstract"), answer("Abstract written.")],
    }


class ScriptedModel:
    """A DGS model adapter that plays a script instead of asking an AI."""

    def __init__(self, script=None, delay: float = 0.0):
        self.script = script or demo_script()
        self.delay = delay
        self.calls = []

    def __call__(self, messages):
        if self.delay:
            import time

            time.sleep(self.delay)
        payload = payload_of(messages)
        node = payload["node"]["id"]
        self.calls.append((node, messages[0]["content"]))
        steps = self.script[node]
        step = steps[min(len(payload.get("history") or []), len(steps) - 1)]
        return step(payload) if callable(step) else step
