# Research on English literature

Use this graph for a review in **literary studies on literature in English**:
an author (Jane Austen, Toni Morrison), a work, a period or movement
(Romanticism, modernism, the Victorian novel), a genre, or a theme across
texts (madness in Victorian fiction, the city in modernist poetry).

Literary scholarship differs from the sciences in ways that change the search:

- the anchors are names of authors and works, and the critical approaches
  (feminist, postcolonial, ecocritical, narratological, historicist);
- much of the important work is in books and book chapters, and citation
  counts are low, so sorting by citations misses central work;
- arXiv has no literary studies, so the graph searches only OpenAlex.

The graph runs four nodes:

1. **plan** - four query sets: primary authors and works with their variants,
   critical approaches, historical and cultural context, recent debates;
2. **criticism** and **context** (in parallel) - run the query sets on
   OpenAlex: criticism on the texts and approaches, context and recent
   debates (newest first);
3. **coverage** - checks the library against the scope: every primary text
   and approach, books as well as articles, the whole time span. It reports
   the gaps with queries to fill them.

It adds the papers to the library and returns the query sets, what the
searches found and the gaps.
