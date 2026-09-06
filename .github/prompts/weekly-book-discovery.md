# Discover one related book

Add exactly one worthwhile non-fiction book to this library's processing queue.
This is discovery and scaffolding only: do not write the briefs, review, rating,
or narration, and do not commit or push anything.

Read `AGENTS.md` first. Then inspect `data/catalog.json`,
`data/relationships.json`, and the completed book profiles. Research outwards
from relationships already represented in the app. Look for a book that a
catalogued work cites, answers, influenced, contrasts with, or makes a strong
next read. It must not already appear in the catalogue under its title,
alternate title, author, or ISBN.

Use web search to verify the candidate against authoritative sources. Prefer
the publisher, author, library catalogue, or another primary bibliographic
source, plus an independent source that supports the relationship. Choose one
candidate only, even if several look good.

Run `./bookflow init --discovered --title "..." --author "..."` to create the
standard scaffold and queue entry. In the new book's `book.json`, record the
sources needed to substantiate the discovery while leaving its workflow as a
metadata-only stub. Add at least one typed edge in `data/relationships.json`
between the new book and a book that was already catalogued before this run.
Give the edge a specific explanation, honest basis and confidence, and valid
`source_refs` pointing into the new book profile. Do not modify existing
catalogue, queue, or relationship entries.

Write `/tmp/weekly-book-discovery.json` with this exact shape:

```json
{
  "book_id": "the-new-book-id",
  "title": "The New Book",
  "author": "Primary Author",
  "relationship_id": "the-added-relationship-id",
  "related_book_id": "an-existing-book-id",
  "rationale": "One concise sentence explaining why this belongs in the graph.",
  "sources": ["https://authoritative.example/book"]
}
```

Before finishing, run:

```bash
./bookflow check --no-local-audio
./bookflow build
./bookflow test
```

Fix any failure. The surrounding workflow independently checks that exactly
one book was added, that it is queued as a discovery, that it connects to an
existing book, and that no unrelated files changed.
