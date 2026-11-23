"""Write the skills' sample graphs (skills/<skill>/graphs/<id>.json).

The graphs are defined here, in one place, and written in the format DGS
verifies when a stage runs one with ``skill.<name>.run_graph``: the graph, its
start nodes, an explanation and the SHA-256 of the usage scenario Markdown
next to it. Edit a graph or its ``.md`` file, then run:

    python scripts/skill_graphs.py

The tests check that the files match this script.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTEXT = {"request": "/request", "scope": "/stages/scope"}
STEPS = {"max_steps": 16, "on_step_limit": "answer"}


def node(graph, node_id, name, allowance, instruction, inputs=None, steps=None, **extra):
    return {
        "id": node_id,
        "type": "stage",
        "name": name,
        "inputs": {**CONTEXT, **(inputs or {})},
        "outputs": {"answer": f"/skill_graphs/{graph}/{node_id}"},
        "allowance": allowance,
        "react": {**STEPS, **({"max_steps": steps} if steps else {})},
        "config": {"instruction": instruction},
        **extra,
    }


def chain(*ids):
    return [{"from": a, "to": b} for a, b in zip(ids, ids[1:], strict=False)]


def out(graph, node_id):
    return f"/skill_graphs/{graph}/{node_id}"


G = "english-literature"
ENGLISH_LITERATURE = {
    "skill": "literature-search",
    "id": G,
    "explanation": (
        "Search for a review in literary studies on literature in English: plan four query sets "
        "(primary authors and works, critical approaches, context, recent debates), run them on "
        "OpenAlex in two parallel nodes, then check coverage and report gaps. Search nodes may "
        "only search and list the library; the others only read it."
    ),
    "start": ["plan"],
    "nodes": [
        node(
            G,
            "plan",
            "Plan query sets",
            "lrg-read",
            "Node of the english-literature search graph (literary studies on literature in "
            "English). From the scope write four query sets, 3-6 queries each, mostly in English: "
            "(a) primary authors and works, with name and title variants (e.g. 'Austen' and "
            "'Pride and Prejudice'); (b) critical approaches relevant to the research questions "
            "(feminist, postcolonial, ecocritical, narratological, new historicist, reception ...), "
            "each combined with an author or work; (c) historical and cultural context (period, "
            "publishing, readership); (d) recent debates and new approaches (digital humanities, "
            "adaptation, global anglophone perspectives). Do not search. Answer with the four "
            "sets as lists.",
            steps=4,
        ),
        node(
            G,
            "criticism",
            "Search criticism",
            "lrg-search-only",
            "Node of the english-literature search graph. Run query sets (a) and (b) from the "
            "plan with lit_search_openalex, 20 results each, relevance sort. Literary criticism "
            "has low citation counts and much of it is in books and chapters, so do not sort by "
            "citations except for one query on the main author or work. Do not use arXiv: it has "
            "no literary studies. If a query returns unrelated fields (a 'Gothic' query returning "
            "architecture), add 'novel', 'fiction', 'poetry' or 'literature' to it. Answer with "
            "each query, how many it found and how many were new.",
            inputs={"plan": out(G, "plan")},
            steps=16,
        ),
        node(
            G,
            "context",
            "Search context and debates",
            "lrg-search-only",
            "Node of the english-literature search graph. Run query sets (c) and (d) from the "
            "plan with lit_search_openalex, 15-20 results each; use sort recent for set (d). If "
            "the scope includes criticism in another language, run two queries with that "
            "language code. Do not use arXiv. Answer with each query, how many it found and how "
            "many were new.",
            inputs={"plan": out(G, "plan")},
            steps=14,
        ),
        node(
            G,
            "coverage",
            "Check coverage",
            "lrg-read",
            "Node of the english-literature search graph. List the library (library_list, page "
            "with offset) and check it against the scope: is there criticism on every primary "
            "author and work, on every critical approach in the research questions, books and "
            "chapters as well as articles, older foundational criticism as well as work from the "
            "last ten years? Answer with what is covered, the gaps, and 3-8 queries that would "
            "fill them.",
            inputs={"criticism": out(G, "criticism"), "context": out(G, "context")},
            steps=8,
            join="all",
        ),
    ],
    "edges": [
        {"from": "plan", "to": "criticism"},
        {"from": "plan", "to": "context"},
        {"from": "criticism", "to": "coverage"},
        {"from": "context", "to": "coverage"},
    ],
}

G = "empirical-education"
EMPIRICAL_EDUCATION = {
    "skill": "screening-extraction",
    "id": G,
    "explanation": (
        "Screen and extract for a review of empirical education research: PICOS criteria with "
        "exclusion codes, title-and-abstract screening, full-record decisions on unclear cases, "
        "then structured extraction (design, participants, intervention, outcomes, results, "
        "limitations). Screening nodes may only read and decide; the extraction node may only "
        "read and take notes."
    ),
    "start": ["criteria"],
    "nodes": [
        node(
            G,
            "criteria",
            "PICOS criteria",
            "lrg-read",
            "Node of the empirical-education screening graph. Turn the scope into PICOS "
            "criteria for education research: Population (learners or teachers, level, setting), "
            "Intervention or phenomenon, Comparison (if any), Outcomes (learning, attainment, "
            "motivation, practice ...), Study design (empirical studies - experimental, "
            "quasi-experimental, correlational, survey, qualitative, mixed - unless the scope "
            "also wants conceptual work). Then list exclusion codes: E1 off topic, E2 wrong "
            "population or setting, E3 not empirical, E4 outside years or languages, E5 "
            "duplicate or superseded, E6 lower priority. Do not call tools except library_list "
            "once to see the pool size. Answer with the criteria and codes.",
            steps=3,
        ),
        node(
            G,
            "title-abstract",
            "Screen titles and abstracts",
            "lrg-screen-only",
            "Node of the empirical-education screening graph. Screen every candidate: page "
            "through library_list (status candidate, detail abstract, offset) and decide with "
            "library_decide, 10-40 papers per call. Reasons start with the code from the "
            "criteria ('E3: position paper'); includes give the design ('include: "
            "quasi-experiment, Year 8'). Leave a paper as candidate with reason 'unclear: ...' "
            "only when the abstract does not show the design or population. Answer with the "
            "counts per code and the number left unclear.",
            inputs={"criteria": out(G, "criteria")},
            steps=40,
        ),
        node(
            G,
            "borderline",
            "Decide unclear cases",
            "lrg-screen-only",
            "Node of the empirical-education screening graph. Read the records of the papers "
            "still candidate (library_list status candidate, then library_get) and include or "
            "exclude each with the code. When the record still does not say, include it if the "
            "title is clearly an empirical study on the topic, with reason 'include: check full "
            "text'. If more papers are included than request.target_papers plus a third, exclude "
            "the weakest with E6 (small or descriptive studies, older work superseded by larger "
            "ones). Answer with the final counts.",
            inputs={"criteria": out(G, "criteria"), "screening": out(G, "title-abstract")},
            steps=14,
        ),
        node(
            G,
            "extract",
            "Extract study data",
            "lrg-note-only",
            "Node of the empirical-education screening graph. For each included paper "
            "(library_list status included; library_get up to 8 at a time) save notes with "
            "library_note, up to 10 papers per call, in the review language: summary; method = design and analysis; data = participants "
            "(number, age or level, country, setting) and period; findings = main results with "
            "direction and effect sizes or significance when reported; limitations; notes = "
            "intervention details and outcome measures. Write 'not reported' for missing "
            "information. Answer with how many studies were extracted and an overview of designs "
            "and settings.",
            inputs={"criteria": out(G, "criteria")},
            steps=30,
        ),
    ],
    "edges": chain("criteria", "title-abstract", "borderline", "extract"),
}

G = "fast-moving-cs"
FAST_MOVING_CS = {
    "skill": "review-organization",
    "id": G,
    "explanation": (
        "Organize a review of a fast-moving computer science field: a timeline with milestones "
        "and preprint status, a taxonomy of method families (tagged on the papers), a comparison "
        "of the families with notes on comparability, and the open problems. Only the taxonomy "
        "node may tag papers; the others only read."
    ),
    "start": ["timeline"],
    "nodes": [
        node(
            G,
            "timeline",
            "Timeline and milestones",
            "lrg-read",
            "Node of the fast-moving-cs organization graph. List the included papers "
            "(library_list status included) and order them by year. Mark which are preprints "
            "(venue arXiv or type preprint) and which are published. Name the 3-6 milestones that "
            "changed the field (a new method, benchmark or result that later papers build on), "
            "each with its paper id, judged from titles, abstracts, notes and citation counts. "
            "Answer with the timeline by year and the milestones.",
            steps=8,
        ),
        node(
            G,
            "taxonomy",
            "Method families",
            "lrg-tag-only",
            "Node of the fast-moving-cs organization graph. Group the included papers into 3-6 "
            "method families by their core technical idea, not by application. Read records with "
            "library_get where the notes are not enough. Tag every included paper with "
            "library_tag: its method family first, then optionally 'benchmark' or 'evaluation' "
            "for papers that mainly propose benchmarks or evaluations, or 'survey' for surveys. "
            "Theme names are in the review language. Answer with each family, its defining idea "
            "and its paper ids.",
            inputs={"timeline": out(G, "timeline")},
            steps=14,
        ),
        node(
            G,
            "compare",
            "Compare the families",
            "lrg-read",
            "Node of the fast-moving-cs organization graph. Compare the method families in a "
            "Markdown table: core idea; typical benchmarks and data; reported strengths; "
            "limitations; representative papers (ids). Below the table, note where results are "
            "not comparable (different benchmarks, settings, model sizes, compute) and where "
            "papers disagree. Use only the records and notes (library_get). Answer with the table "
            "and the notes.",
            inputs={"taxonomy": out(G, "taxonomy")},
            steps=10,
        ),
        node(
            G,
            "gaps",
            "Open problems",
            "lrg-read",
            "Node of the fast-moving-cs organization graph. From the timeline, taxonomy and "
            "comparison, answer with: the open problems the papers name or leave unanswered; "
            "evaluation and reproducibility issues; which directions are changing fastest; and "
            "cautions for the review, such as how many included papers are unreviewed preprints "
            "and which claims rest only on them.",
            inputs={
                "timeline": out(G, "timeline"),
                "taxonomy": out(G, "taxonomy"),
                "compare": out(G, "compare"),
            },
            steps=4,
        ),
    ],
    "edges": chain("timeline", "taxonomy", "compare", "gaps"),
}

G = "chinese-gbt7714"
CHINESE_GBT7714 = {
    "skill": "review-writing",
    "id": G,
    "explanation": (
        "Write a literature review in Simplified Chinese with GB/T 7714 references: a glossary "
        "of key terms, a draft of every outline section in Chinese academic style, then a "
        "revision pass for register, terminology and synthesis. Only the draft and polish nodes "
        "may write sections."
    ),
    "start": ["glossary"],
    "nodes": [
        node(
            G,
            "glossary",
            "Terminology glossary",
            "lrg-read",
            "Node of the chinese-gbt7714 writing graph. Read the outline (it is in the context as "
            "outline, or use the included papers with library_list) and build a glossary of the "
            "15-40 key terms of this review: each English term with its established Simplified "
            "Chinese translation (术语), one translation per term, plus the convention for author "
            "names (Latin spelling with family name only in running text). Answer with the "
            "glossary as a table.",
            inputs={"outline": "/stages/outline"},
            steps=4,
        ),
        node(
            G,
            "draft",
            "Draft in Chinese",
            "lrg-write-only",
            "Node of the chinese-gbt7714 writing graph. Write every section of the outline "
            "(review_outline) in Simplified Chinese written academic style (书面语) with "
            "review_write_section, one call per section, in outline order; no abstract. Before "
            "each theme section read its papers with library_get. Use the glossary's terms, with "
            "the English in parentheses at first mention. Cite with library ids before the "
            "closing punctuation: …存在显著差异 [P3, P7]。 Synthesize several papers per "
            "paragraph; topic sentence first. The method section reports the real sources, "
            "queries and counts (library_list). Answer with the sections and their lengths.",
            inputs={
                "outline": "/stages/outline",
                "organize": "/stages/organize",
                "glossary": out(G, "glossary"),
            },
            steps=30,
        ),
        node(
            G,
            "polish",
            "Revise the Chinese text",
            "lrg-write-only",
            "Node of the chinese-gbt7714 writing graph. Read each section (review_read with "
            "section_id) and revise it with review_write_section where needed: written register "
            "instead of colloquial words, no translationese (被…所…, chains of 的, 进行…的研究), "
            "consistent terms from the glossary, full-width Chinese punctuation and half-width "
            "numbers, citations before closing punctuation, and paragraphs that compare papers "
            "instead of listing them. Keep every citation that is correct. Answer with what you "
            "revised in each section.",
            inputs={"glossary": out(G, "glossary"), "draft": out(G, "draft")},
            steps=24,
        ),
    ],
    "edges": chain("glossary", "draft", "polish"),
}

GRAPHS = [ENGLISH_LITERATURE, EMPIRICAL_EDUCATION, FAST_MOVING_CS, CHINESE_GBT7714]


def document(graph: dict) -> dict:
    folder = ROOT / "skills" / graph["skill"] / "graphs"
    scenario = (folder / f"{graph['id']}.md").read_bytes()
    return {
        "usage_scenario_file": f"{graph['id']}.md",
        "usage_scenario_sha256": hashlib.sha256(scenario).hexdigest(),
        "graph": {"nodes": graph["nodes"], "edges": graph["edges"], "depth": 1},
        "start": graph["start"],
        "explanation": graph["explanation"],
    }


def render(graph: dict) -> str:
    return json.dumps(document(graph), ensure_ascii=False, indent=2) + "\n"


def path(graph: dict) -> Path:
    return ROOT / "skills" / graph["skill"] / "graphs" / f"{graph['id']}.json"


def main() -> int:
    for graph in GRAPHS:
        path(graph).write_text(render(graph), "utf-8")
        print("wrote", path(graph).relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
