# Screening edge cases

- **Duplicates.** The library merges records with the same DOI, arXiv id or
  title. A preprint and its published version can still both appear with
  different titles: keep the published version, exclude the other with
  `E5 superseded by P..`.
- **Reviews and surveys.** Include them if the scope wants them as sources;
  otherwise use them to check coverage and exclude them with a reason
  (`E3: review article, used for coverage`).
- **Books and chapters.** Judge by title, venue (publisher) and year when
  there is no abstract. Central books in the humanities often have none.
- **Language.** Exclude papers in languages the scope excludes, with the
  code. Do not exclude a paper only because its abstract is in another
  language.
- **Years.** The search already limits years, but records can have wrong
  years (reprints, new editions). Follow the scope.
- **Off-topic hits.** Search engines return papers that share words but not
  the topic (an "irony" paper in chemistry). Exclude them with `E1`.
- **Uncertain.** Leave a paper as `candidate` only while you are still
  screening; at the end every candidate is included or excluded.
