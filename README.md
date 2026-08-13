# Books

A research-backed book library for deciding what to read, listen to, borrow, or buy.

Each book has concise structured metadata, a readable analysis, cited research, and optional audio scripts. Authors and books are connected through a small typed graph so the library can recommend useful next reads without duplicating relationship lists in every profile.

Start with [AGENTS.md](AGENTS.md). The first example is [Alchemy by Rory Sutherland](library/books/alchemy-rory-sutherland/summary.md).

## Design

- Markdown holds summaries and narration scripts.
- JSON holds metadata, citations, workflow state, tags, and relationships.
- `taxonomy/tags.json` prevents uncontrolled tag variants.
- `data/catalog.json` provides the discoverable entity index.
- `data/relationships.json` provides traversable book-author-idea connections.

Audio targets default to 150 words per minute. See `config/audio.json` for the duration presets and the retained 250-WPM alternative.
