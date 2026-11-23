---
name: literature-search
description: Plan and run the literature search of a review - turn research questions into concepts, synonyms and queries, choose sources (OpenAlex, arXiv), find reviews, classics and recent work, fill gaps and decide when the search is complete. Use in the search stage, and when writing search queries for a scope.
license: MIT
metadata:
  version: "1.0"
---

# Doing a literature search

A good search finds the work a specialist would expect to see cited, plus the
recent work they may not know yet, and it can be reported honestly: which
sources, which queries, how many results.

## Steps

1. **Concepts.** Split each research question into 2-4 concepts (for example
   *irony* + *Austen* + *narrative voice*). For each concept list synonyms,
   broader and narrower terms, spelling variants and, where the field publishes
   in another language, the terms in that language. Read
   `references/query-building.md`.
2. **Choose sources.** OpenAlex covers every field (journals, books, chapters,
   theses, conference papers). arXiv only covers preprints in physics,
   mathematics, computer science, statistics and neighbouring fields. Read
   `references/sources.md`.
3. **Broad first.** Run the core queries (concept A + concept B) with
   relevance sorting, 15-25 results each.
4. **Reviews and classics.** Add "review", "survey", "overview" or
   "meta-analysis" to a core query; run one core query with `sort: cited`.
5. **Recent work.** Run core queries with `sort: recent` or `from_year`.
6. **Gaps.** Look at what came back (`library_list`). For each research
   question and each approach in the scope, is there relevant work? Search
   for what is missing with new terms, not the same query again.
7. **Stop** when new queries return mostly papers already in the library
   (`new` is small in the reply) or the candidate pool is three to four times
   the number of papers the review should include.

Report the queries per source and what each found: the method section of the
review is written from it.

## Saved graphs

`graphs/` holds graphs for specific kinds of review. Run one with
`run_graph` when its usage scenario matches the review. Afterwards, check the
gaps it reports and search for them yourself.
