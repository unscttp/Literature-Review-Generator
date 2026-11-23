# Building search queries

## From questions to queries

| Step | Example (topic: irony in Jane Austen's novels) |
| --- | --- |
| Concepts | irony; Austen; narration |
| Synonyms and variants | irony, ironic, satire; Jane Austen, Pride and Prejudice, Emma; free indirect discourse, narrative voice, narrator |
| Core queries | `Austen irony`, `Austen free indirect discourse`, `"Pride and Prejudice" irony` |
| Reviews | `Austen criticism review`, `Jane Austen studies survey` |

## Rules of thumb

- Two or three concepts per query. One word is too broad; five words often
  find nothing.
- Put exact phrases in double quotes: `"free indirect discourse"`.
- OpenAlex understands AND, OR and NOT in capitals:
  `(irony OR satire) AND Austen`. arXiv queries are combined with AND.
- Search in English first: most indexed work has an English title or
  abstract. Add a query in the field's own language where much is published
  in it (Chinese, German, French ...), with `language` set for OpenAlex.
- Use the field's own vocabulary. Read the titles of the first results and
  borrow their terms for the next query.
- If a query returns nothing or the wrong field, change the terms: add the
  discipline (`irony narratology`), remove a concept, or use a synonym.
  Never repeat a query that failed.
- Names of people and works are precise anchors in the humanities; method
  and dataset names are precise anchors in the sciences.

## When is the search done?

- Each research question has relevant results.
- The well-known works of the field appear (highly cited, or the ones the
  reviews cite).
- New queries mostly return papers that are already in the library.
