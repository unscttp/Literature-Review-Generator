**English** | [简体中文](README.zh-CN.md)

# Literature Review Generator

Give it a topic and it produces a literature review with real, checkable
references. The work runs in eight stages that you can watch: you approve
the scope, then the app searches OpenAlex and arXiv, screens the results,
takes notes, organizes the papers into themes, plans the outline, writes the
review and checks it. The interface and the reviews are in English or
Simplified Chinese.

It is a showcase of [Directed Growing Sheet](https://github.com/unscttp/Directed-Growing-Sheet)
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
- **Stages that design their own graphs.** When no saved graph fits, the
  search, screening, organizing and writing stages may plan a graph of steps
  for this review. You see each graph drawn before it runs, with what every
  step may do, and decide whether it runs and whether it is saved into its
  skill, where the next review finds it. The generator grows with use.
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
git clone --recursive https://github.com/unscttp/Literature-Review-Generator
cd literature-review-generator
python install.py
```

`install.py` sets up everything in a private folder (`.venv`) and runs the
tests. Then start the app:

```bash
python run.py
```

Your browser opens http://127.0.0.1:8765. Keep the terminal open while you
use the app; Ctrl+C stops it.

**Choose the model in the app.** At the top of the new-review page, pick the
service (Google Gemini, Anthropic Claude, OpenAI GPT, DeepSeek, Ollama or LM
Studio on your computer, or any other OpenAI-compatible API), paste its API key
and save it. The model list then comes from the service itself: it shows the
models your key can use, with the suggested one first (Gemini 4 Hydrogen,
Claude Opus 5.5, GPT-6.2 Astra, DeepSeek V4 Pro). **Test** sends one small
request to check the choice. Each review keeps the model it was started with;
the last choice is preselected for the next one.

**Try it without a model first:**

```bash
python run.py --demo
```

The demo runs a scripted review on a few made-up example records: no AI, no
key, no network. It shows every stage, the scope approval, a sample graph
and a graph the organize stage designs and offers to save; run a second demo
review and the stage reuses the saved graph.

Downloaded the ZIP instead of using git? `install.py` fetches DGS by itself.

## Writing a review

1. **New review.** Choose the model, describe the topic and choose the review language, the
   citation style, the kind of review (narrative, scoping or systematic-style),
   the publication years, how many papers to include and the sources.
2. **Approve the scope.** After a minute the scope appears. Approve it, or
   write what should change and send it back.
3. **Approve the graphs.** When a stage wants to run a graph (a skill's saved
   graph, or one it designed for this review), it shows you the graph first:
   its steps, what each may do and why. Approve it, or reject it with a
   comment and the stage continues without it. After a designed graph has
   worked, you decide whether to save it into the skill.
4. **Watch it work.** The *Workflow* tab shows the stages; click one to see its
   result. *Library* lists every paper found, with the screening decision and
   its reason, the notes and the themes. *Activity* lists each tool call.
5. **Read and download.** *Report* shows the review as it is being written,
   with the result of the citation check. Download it as Markdown and the
   references as BibTeX.

**How many model calls?** Each stage has a step limit that grows with the
number of papers to include (`max_steps` in `config/workflow.json` plus
`steps_per_paper` in `config/settings.json`). Screening works through the
whole candidate pool, so its limit grows with the candidates the search found
(`steps_per_candidate`, about one step per eight candidates) when that is more.
The eight stages may make up to about 130 calls for 5 papers, 185 for 25 and
330 for 80 (more when the search finds a large pool), plus up to 120 for each
skill graph a stage runs; the form shows the number for your review. A wide
field uses much of that budget: with skill graphs a large review can approach
1000 calls. Check your provider's rate limits and prices, and raise the limits
in the two files if stages run out of steps. Runs continue in the background;
you can close the browser tab. If the app is stopped during a run, open the review and press
**Resume**: finished steps are not repeated.

## How it works

The workflow is `config/workflow.json`: eight LLM nodes in a chain. Each has
its instruction, a step limit and an **allowance**, the exact list of tools it
may call (`config/allowances/`). DGS checks every tool call against it.

| # | Stage | What it does | Tools it may use |
| --- | --- | --- | --- |
| 1 | Scope | Research questions, criteria, queries; you approve | `scope.submit`, reads the search skill |
| 2 | Search | Searches OpenAlex and arXiv; results go into the library | `lit.search_openalex`, `lit.search_arxiv`, `library.list/get`, literature-search skill and its graph |
| 3 | Screen | Includes or excludes every candidate, with a reason | `library.next_candidates/decide/exclude_remaining`, `library.list/get/note`, screening-extraction skill and its graph |
| 4 | Extract | Notes on method, data, findings, limitations | `library.list/get/note/decide` |
| 5 | Organize | Themes, comparison, gaps | `library.list/get/tag`, review-organization skill and its graph |
| 6 | Outline | Sections and the papers each cites | `library.list/get`, `review.set_outline` |
| 7 | Write | The sections, citing library ids | `library.list/get`, `review.write_section/read`, review-writing skill and its graph |
| 8 | Review | Fixes what the check finds, writes the abstract | `review.check/read/write_section` |

The stages pass their results on through the task's data (`/stages/<id>`);
the library, the outline and the sections are files in the run's folder
(`data/runs/<id>/`). Only stage 2 can reach the network, and only the
scholarly APIs. No stage can read or write other files.

**The scope approval** is a DGS human check inside the `scope.submit` tool,
marked `"on_reject": "continue"`: when you send the scope back, the tool
returns your comment to the model instead of ending the run.

**Stage checks.** A stage's answer is only a summary, so it counts only once
the work is really done. Each stage names a DGS result check
(`react.result_check` in `config/workflow.json`, the checks are in
`lrg/gates.py`), which looks at the library and the text when the model
answers:

| Stage | Accepted when |
| --- | --- |
| Scope | You approved the scope |
| Search | The library has papers |
| Screen | No candidate is left undecided and at least one paper is included |
| Extract | Every included paper has notes |
| Organize | Every included paper has a theme |
| Outline | The outline is saved and plans every included paper |
| Write | Every section of the outline is written |
| Review | No blocking issue: citations of unknown or not-included papers, unwritten sections, a missing abstract |

If something is missing, the answer is rejected and the model is told what
(it shows as *Result not accepted* under *Activity*), and the stage goes on.
A stage that runs out of steps with work missing fails with that reason, and
the next stage does not start: the run stops instead of producing a review
that only looks finished. **Resume** gives the stage fresh steps. The tools
hold the same line: only included papers can get notes and themes, be
planned in the outline or be cited, and `library.exclude_remaining` closes a
large screening in one call once the papers to include are chosen.

**Screening large pools.** A search can find hundreds of candidates; read
page by page, they no longer fit in the model's context, and a model that
reads everything before deciding runs out of steps with nothing decided.
Screening therefore uses a queue: `library.next_candidates` hands out 25
undecided candidates with their abstracts and the progress, and hands out the
next batch only once these are decided (a paper put back to *candidate* comes
again at the end). Decisions are saved batch by batch, whatever the model
still remembers.

**Keeping long stages small.** Every model call sends the stage's context
again, so long stages used to dominate the token count. With DGS 1.3 a call
carries only the stage's newest steps in full (5 by default; 2 in Screen,
whose earlier batches are decided and saved) and every failed step; older
steps become a numbered index, one line each, folded per ten
(`react_full_steps` and `react_index_fold` in `config/settings.json`, and
`react.full_steps` per stage in `config/workflow.json`). Each tool writes its
own index line ("library.decide - 25 decisions (2 include); now 2 included,
48 excluded, 225 candidates"), and the model reads an old step back with
`history_read` when it needs the details. In a test review with 275
candidates this halved the characters sent; the stage panel of the viewer
shows each stage's tokens.

When a stage fails, the error says what it did: its tool calls by name, how
many failed, how many answers were not accepted and the last tool error.

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

### Graphs the stages design

Search, Screen, Organize and Write have `allow_create_graph: true` and
`graph.create` in their allowances. Their instructions say: run a saved graph
of the skill if one fits; otherwise, when the work splits into clear steps,
design a graph for this review with `graph_create`: 2-5 nodes of type `stage`,
each with its instruction and one of the narrower allowances the instruction
names (for example `lrg-tag-only` in Organize: read the library and assign
themes, nothing else), plus `save_to_skill` and a usage scenario in Markdown.
Then DGS:

1. **checks** the proposal: the node types must be allowed in generated graphs
   and every node's allowance must be a subset of the stage's; otherwise the
   call fails and the model is told why;
2. **asks you** (`graph_creation_human_check`, on for every graph): the
   approval card draws the graph with the viewer and lists each step's
   permissions and instruction. Rejecting it does not fail the stage: the
   model gets your comment and continues without the graph;
3. **runs** it as a child task of the stage, shown under the stage in the
   viewer as *Graph designed by the model*;
4. **asks again** before saving it (`graph_save_human_check`), and writes it
   to `data/skills/<skill>/graphs/<id>.json` with its usage scenario;
5. **offers it** to later reviews: `skill.<name>.invoke` lists it next to the
   sample graph, with its run history and a hint when the model or the
   permissions changed since it last worked. The start page lists saved
   graphs with *saved from a review*; **Remove** deletes one.

The new-review form has *Stages may design their own graphs* (on by default);
switched off, the stages can still run saved graphs but not design new ones.

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
| `config/models.json` | The services the model menu offers and their suggested models |
| `.lrg/config.json` | Your API keys (one per service) and last model choice, readable only by you |
| `.lrg/settings.json` | Your OpenAlex key (set in the app's settings) |
| `data/` | Your reviews and the installed skills |

Keys are saved on your computer only and sent only to their own service; the
browser never gets them back. Remove them under *Settings*. If you prefer the
terminal, `python run.py --setup` asks the same questions there. The
environment variables `DGS_API_KEY`, `DGS_MODEL` and `DGS_BASE_URL` override the
saved choice, and `LRG_OPENALEX_API_KEY` the OpenAlex key.

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
| "The model list could not be loaded: HTTP 401" | The service refused the key: paste it again (**Change key**). |
| The model you want is not in the list | Choose **Other model ID…** and type it, or press ↻ to ask the service again. |
| Ollama or LM Studio: "Could not connect" | Start Ollama or LM Studio's local server first. |
| "Cannot use port 8765" | Another program uses it: `python run.py --port 8766`. |
| A stage fails with HTTP 401 or 403 | The key was not accepted: save it again in the model section, then **Resume**. |
| A stage failed: "the result was not accepted: ..." | The stage ran out of steps before its work was done (the message says what is missing). Press **Resume** for fresh steps, or raise its limit in `config/settings.json`. |
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
| `lrg/model.py` | Services, API keys, live model lists and the per-review model choice |
| `lrg/gates.py` | The stage checks: what each stage must have done before its answer counts |
| `lrg/demo.py` | The scripted demo model |
| `web/` | The interface: plain HTML, CSS and JavaScript; texts in `web/i18n/` |
| `third_party/dgs` | Directed Growing Sheet (git submodule) |

## License

Licensed under the [Apache License 2.0](LICENSE).
