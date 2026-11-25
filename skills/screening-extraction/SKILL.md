---
name: screening-extraction
description: Screen candidate papers against a review's inclusion and exclusion criteria with recorded reasons, and extract comparable evidence (method, data, findings, limitations) from the included papers. Use in the screen and extract stages.
license: Apache-2.0
metadata:
  version: "1.0"
---

# Screening and extraction

Screening decides which candidates the review is about; extraction records,
for every included paper, the same kinds of information so they can be
compared. Both must be traceable: every exclusion has a reason that names a
criterion, and every note comes from the paper's record.

## Screening

1. Restate the criteria as a short checklist with codes, for example
   `E1 not about the topic`, `E2 wrong population`, `E3 not a research
   publication`, `E4 outside the years`, `E5 duplicate or superseded`.
2. Screen with the queue: `library_next_candidates` gives the next 25
   undecided candidates with their abstracts. Decide all of them with one
   `library_decide` call, then ask for the next batch. Decide each batch
   before reading further: with hundreds of candidates, a batch you only read
   drops out of view, and every call uses a step. Start the reason with the
   code: `E2: secondary school students`.
3. Include on the title and abstract when they clearly meet the criteria.
   When the abstract is missing or unclear, read the record (`library_get`);
   if it is still unclear, include it when the title is clearly on topic and
   note `check full text` in the reason.
4. Balance: if far more papers qualify than the review should include, keep
   the most relevant, the most substantive (empirical studies and major
   theoretical works over short notes) and a spread of approaches and years.
   Exclude the rest with `E6 lower priority`, so the choice is visible.
5. Report the counts per reason: the method section needs them.

Read `references/screening.md` for edge cases.

## Extraction

For each included paper save with `library_note` (up to 10 papers per call):

- **summary** - one or two sentences: what the paper does;
- **method** - design or approach (experiment, survey, case study, corpus
  analysis, close reading, model and benchmark ...);
- **data** - what it studies: sample, corpus, texts, dataset, period;
- **findings** - the main results as the abstract states them;
- **limitations** - stated or evident (small sample, single site, preprint);
- **notes** - anything the review needs: theory used, key terms, relation to
  other papers in the library.

Write `not reported` instead of guessing. Read `references/extraction.md`.

## Saved graphs

`graphs/` holds graphs for specific kinds of review. Run one with
`run_graph` when its usage scenario matches the review.
