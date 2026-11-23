# The sources

## OpenAlex (`lit_search_openalex`)

- An open index of more than 250 million works: journal articles, books,
  book chapters, theses, conference papers and preprints, in all fields and
  languages.
- Searches titles, abstracts and full text where available.
- `sort: cited` finds the classics, `sort: recent` the newest work;
  `from_year` and `to_year` limit the years; `language` (ISO 639-1 code,
  `en`, `zh`, `de` ...) limits the language.
- Citation counts differ a lot between fields: a humanities book with 50
  citations can be central; a computer science paper with 50 can be minor.
- Abstracts are missing for some works (often books and older articles).
  Judge those by title and venue and mark them for checking.
- Without an API key there is a shared daily budget. If a reply says the
  budget is used up, stop calling OpenAlex in this run.

## arXiv (`lit_search_arxiv`)

- Preprints in physics, mathematics, computer science, quantitative biology,
  quantitative finance, statistics, electrical engineering and economics.
- Not peer reviewed: a preprint may change or never be published. Note this
  when a review relies on preprints; a record with a journal reference
  (venue other than arXiv) was published.
- Categories narrow a search: `cs.CL` (computational linguistics), `cs.LG`
  (machine learning), `cs.AI`, `cs.CV`, `stat.ML`, `econ.EM` ...
- Useless for the humanities, most social sciences, medicine and law: do not
  use it there.
- arXiv asks for one request every three seconds; the tool waits by itself.
