**English** | [简体中文](README.zh-CN.md)

# Literature Review Generator

Give it a topic and it produces a literature review with real, checkable
references. The work runs in eight stages that you can watch: you approve
the scope, then the app searches OpenAlex and arXiv, screens the results,
takes notes, organizes the papers into themes, plans the outline, writes the
review and checks it. The interface and the reviews are in English or
Simplified Chinese.

It is a showcase of [Directed Growing Sheet](https://github.com/unscttp/directed-growing-sheet)
(DGS), a JSON-first workflow engine for AI agents. Everything that makes a
review trustworthy is enforced by DGS rather than by asking the model nicely:
what each stage may do, when you are asked, which papers can be cited.

- **No invented references.** Every paper comes from a search result and gets
  an id in the review's library (P1, P2 ...). The model cites ids; the
  reference list is generated from the library records in APA 7, GB/T
  7714-2015 or MLA 9, with a BibTeX file. A check flags citations of papers
  that are unknown or were not included.
- **You approve the scope.** Before anything is searched, you see the research
  questions, criteria and search queries. Approve them, or send them back with
  a comment: the model revises and asks again.
- **A live workflow viewer.** The eight stages, which one is working and on
  what. When a stage runs one of the skills' sample graphs, that graph appears
  under it with its own nodes.
- **Skills with sample graphs.** Four Agent Skills guide the stages: doing a
  literature search, screening and extraction, organizing a review and
  writing a review. Each comes with a graph for one kind of review (English
  literature, empirical education research, a fast-moving computer science
  field, a review in Chinese with GB/T 7714).
- **Bilingual.** English and Simplified Chinese interface, reviews in either
  language, sources in any language.

## Quick start

You need **Python 3.10 or newer** (check with `python --version`; on Windows,
tick "Add python.exe to PATH" when installing it) and an **API key** for the
model you want to use: Gemini, Claude, GPT or DeepSeek. A model running on
your own computer with Ollama or LM Studio needs no key.

```bash
git clone --recursive https://github.com/unscttp/literature-review-generator
cd literature-review-generator
python install.py
```

`install.py` sets up everything in a private folder (`.venv`), runs the tests
and asks which model to use (Gemini 4 Hydrogen unless you choose another).
Then start the app:

```bash
python run.py
```

Your browser opens http://127.0.0.1:8765. Keep the terminal open while you
use the app; Ctrl+C stops it.

**Try it without a model first:**

```bash
python run.py --demo
```

The demo runs a scripted review on a few made-up example records: no AI, no
key, no network. It shows every stage, the scope approval and a skill graph.

Downloaded the ZIP instead of using git? `install.py` fetches DGS by itself.

## Writing a review

1. **New review.** Describe the topic and choose the review language, the
   citation style, the kind of review (narrative, scoping or systematic-style),
   the publication years, how many papers to include and the sources.
2. **Approve the scope.** After a minute the scope appears. Approve it, or
   write what should change and send it back.
3. **Watch it work.** The *Workflow* tab shows the stages; click one to see its
   result. *Library* lists every paper found, with the screening decision and
   its reason, the notes and the themes. *Activity* lists each tool call.
4. **Read and download.** *Report* shows the review as it is being written,
   with the result of the citation check. Download it as Markdown and the
   references as BibTeX.

The stages' step limits allow up to about 200 model calls per review; how
long that takes depends on the model and its rate limits. Runs continue in the
background; you can close the browser tab. If the app is stopped during a run, open the review and press
**Resume**: finished steps are not repeated.

## How it works

The workflow is `config/workflow.json`: eight LLM nodes in a chain. Each has
its instruction, a step limit and an **allowance**, the exact list of tools it
may call (`config/allowances/`). DGS checks every tool call against it.

| # | Stage | What it does | Tools it may use |
| --- | --- | --- | --- |
| 1 | Scope | Research questions, criteria, queries; you approve | `scope.submit`, reads the search skill |
| 2 | Search | Searches OpenAlex and arXiv; results go into the library | `lit.search_openalex`, `lit.search_arxiv`, `library.list/get`, literature-search skill and its graph |
| 3 | Screen | Includes or excludes every candidate, with a reason | `library.list/get/decide/note`, screening-extraction skill and its graph |
| 4 | Extract | Notes on method, data, findings, limitations | `library.list/get/note/decide` |
| 5 | Organize | Themes, comparison, gaps | `library.list/get/tag`, review-organization skill and its graph |
| 6 | Outline | Sections and the papers each cites | `library.list/get`, `review.set_outline` |
| 7 | Write | The sections, citing library ids | `library.list/get`, `review.write_section/read`, review-writing skill and its graph |
| 8 | Review | Fixes what the check finds, writes the abstract | `review.check/read/write_section/delete_section` |

The stages pass their results on through the task's data (`/stages/<id>`);
the library, the outline and the sections are files in the run's folder
(`data/runs/<id>/`). Only stage 2 can reach the network, and only the
scholarly APIs. No stage can read or write other files.

**The scope approval** is a DGS human check inside the `scope.submit` tool,
marked `"on_reject": "continue"`: when you send the scope back, the tool
returns your comment to the model instead of ending the run. If a model
answers without submitting a scope, a post-run hook asks you to approve its
answer instead; rejecting it ends the run.

**Citations** are built by `lrg/references.py` from the library records
whenever the report is shown, so the text and the references always agree.
Author names, years and venues come from OpenAlex and arXiv, never from the
model.

**Skills** are Agent Skills in `skills/`: a
`SKILL.md` with guidance and `references/` that the stages read with
`skill.<name>.read`. Each skill's `graphs/` holds one sample graph that DGS
verifies (its usage scenario is hashed) and that a stage may run with
`skill.<name>.run_graph`:

| Skill | Sample graph | For |
| --- | --- | --- |
| literature-search | `english-literature` | Literary studies on literature in English: query sets for authors and works, critical approaches, context and debates; two search nodes in parallel; a coverage check |
| screening-extraction | `empirical-education` | Empirical studies in education: PICOS criteria with exclusion codes, title-and-abstract screening, unclear cases, structured extraction |
| review-organization | `fast-moving-cs` | Computer science fields that move in months: timeline and milestones, method families, comparison, open problems and preprint caveats |
| review-writing | `chinese-gbt7714` | Reviews in Simplified Chinese with GB/T 7714: glossary, draft in academic Chinese, revision pass |

A graph's nodes get narrower allowances than the stage that runs it (DGS
refuses to run a graph that would get more). After each run DGS records in
`data/skills/<skill>/graphs/<id>.meta.json` how it went and with which model, so the stage is told
when a graph last worked under different conditions.

**The viewer** follows the run through DGS run observers, which report every
node execution, including those of a skill graph while it runs.

Other DGS features in use: automatic retries of model calls that time out or
hit rate limits, an answer instead of a failure when a stage reaches its step
limit, and the action journal that lets a stopped run resume without
repeating finished tool calls.

## Configuration

| File | What |
| --- | --- |
| `config/workflow.json` | The stages: instructions, step limits, allowances |
| `config/allowances/*.json` | What each stage (and each skill-graph node) may do |
| `config/rules.md` | Rules every stage receives: never invent literature, cite by id, language |
| `config/settings.json` | Port, DGS engine settings, defaults of the new-review form |
| `skills/` | The skills and their sample graphs (after editing a graph, run `python scripts/skill_graphs.py`) |
| `.lrg/config.json` | Your model choice and key (created by the setup; only on your computer) |
| `.lrg/settings.json` | Your OpenAlex key (set in the app's settings) |
| `data/` | Your reviews and the installed skills |

To use another model: `python run.py --setup`. The environment variables
`DGS_API_KEY`, `DGS_MODEL` and `DGS_BASE_URL` override the saved model, and
`LRG_OPENALEX_API_KEY` the OpenAlex key.

**OpenAlex** works without a key, but everyone without a key shares a daily
budget. A free key from [openalex.org](https://openalex.org) gives you your own;
enter it under *Settings*. **arXiv** needs no key; the app waits three
seconds between requests, as arXiv asks.

## Limits

- The stages read titles, abstracts and metadata, not full texts. Notes say
  "not reported" where an abstract is silent, but a review based on
  abstracts misses what only the full text says.
- Screening and synthesis are done by an AI model. Treat the review as a
  well-sourced first draft: check the included papers and the claims made
  about them before you rely on it.
- OpenAlex and arXiv cover a great deal but not everything (some publishers,
  many non-English journals, grey literature). The method section reports
  what was searched.
- Metadata can be incomplete (missing issue numbers, unusual capitalisation),
  so check the formatted references before submitting.

## If something goes wrong

| Message | What to do |
| --- | --- |
| "No model is chosen yet" | Run `python run.py --setup`. |
| "Cannot use port 8765" | Another program uses it: `python run.py --port 8766`. |
| A stage fails with HTTP 401 or 403 | The key was not accepted: `python run.py --setup`. |
| Timeouts or HTTP 429 from the model | The service is busy; DGS retries by itself. Press **Resume** if the run stopped. |
| "OpenAlex refused the request: ... budget" | Add a free OpenAlex key under *Settings*, or wait until tomorrow. |
| "Directed Growing Sheet is missing" | Run `python install.py`. |

## For developers

```bash
python -m unittest discover -s tests -t .
```

The tests run complete reviews with the scripted demo model and fake sources,
so they need no key and no network. The code:

| Path | What |
| --- | --- |
| `lrg/pipeline.py` | Runs: one DGS task per review, in a background thread |
| `lrg/tools.py` | The review's tools, one DGS tool module per run |
| `lrg/library.py`, `lrg/report.py`, `lrg/references.py` | Library, sections and checks, citation styles |
| `lrg/sources.py` | OpenAlex and arXiv (standard library only) |
| `lrg/graph_view.py`, `lrg/live.py` | The data behind the workflow viewer |
| `lrg/server.py` | The local web server (standard library only) and its JSON API |
| `lrg/demo.py` | The scripted demo model |
| `web/` | The interface: plain HTML, CSS and JavaScript; texts in `web/i18n/` |
| `third_party/dgs` | Directed Growing Sheet (git submodule) |
