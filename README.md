# 5MinBooks

A local, research-backed non-fiction library for deciding what to read, listen to, borrow, or buy.

The UI presents each book at progressively deeper levels. The current levels
and targets live in [`config/audio.json`](config/audio.json); their research
basis is in [the content model](docs/research-and-content-model.md).

## Use it

Requirements: Python 3.10 or later and [uv](https://docs.astral.sh/uv/). The library app itself has no JavaScript build step.

```bash
./bookflow check
./bookflow serve
```

`./bookflow test` runs the unit tests for the shared tooling (rating
arithmetic and pronunciation matching); run it after changing anything in
`scripts/`.

`serve` builds the browser data and opens the local UI at `http://127.0.0.1:8042/`. It supports search, rating sort, layered briefs, transcripts, playback speed, book and author detail pages with linked relationships, queues, and saved playlists. Saved playlists use `data/playlists.json` under the local server and browser storage under a plain static server.

Create a book workspace:

```bash
./bookflow init --title "Book title" --author "Author name"
```

An AI agent then follows [AGENTS.md](AGENTS.md) to research and fill the structured files. The command creates the complete scaffold; it does not pretend to research the book.

## Process the queue with an agent

Start either CLI in the repository root, then invoke the project skill in its
prompt. In Codex CLI:

```text
$process-next-book
```

In Claude Code:

```text
/process-next-book
```

The two commands use the same canonical
[skill](.agents/skills/process-next-book/SKILL.md); the Claude project path is
a symlink, so its instructions cannot drift. The skill claims one ready book,
researches and reviews it, calculates its reputation-blind rating, derives every
configured narration length, hands local audio generation to `bookflow`, validates
the repository, and updates the queue. If a CLI session was already open when
the skill directory was first added, restart it. As a discovery fallback, use
this plain prompt: `Read .agents/skills/process-next-book/SKILL.md and follow it
to process the next queued book.` See the official [Codex skill
guide](https://developers.openai.com/codex/skills) and [Claude Code skill
guide](https://code.claude.com/docs/en/slash-commands) for discovery and
invocation details.

Narration contains the book treatment only. Sources, coverage, fact-checking
notes and production details stay in the structured records and sidecars; they
are never read aloud. Every configured duration must have a transcript and
local audio before a book is complete.

The rating total is deterministic once its evidence-backed component scores
are filled:

```bash
./bookflow rate <book-id>          # inspect the calculated score
./bookflow rate <book-id> --write  # write the calculated total
```

Its rubric lives in `config/rating.json`; the [rating model](docs/rating-model.md)
explains the research basis and limits. It evaluates what is on the page —
the ideas and the reading craft of their delivery — never the author's
identity, popularity, awards, or review score.

Generate approved audio locally with the Apache-licensed [Kokoro model](https://github.com/hexgrad/kokoro) through the lightweight MIT-licensed [Kokoro-ONNX runtime](https://github.com/thewh1teagle/kokoro-onnx):

```bash
./bookflow audio <book-id>             # every approved level for one book
./bookflow audio <book-id> 5-minutes   # one level
./bookflow audio --all                 # every approved script in the library
```

The first run installs the declared Python packages and may download model data. Audio is stored under each book's `audio/` directory; audio and model weights stay local and are not committed. A JSON sidecar records how each file was made and becomes stale after a script or pronunciation-dictionary change. See [the TTS guide](docs/tts.md) before adding or correcting a pronunciation.

Inspect the phonemes and any shared-dictionary match for a difficult term:

```bash
./bookflow pronunciation "author name or specialist term"
```

## Deploy to a static host

`./bookflow build` writes `dist/`: a complete, root-layout static site
(`index.html` at the top, data and audio inside), so the app serves from `/`
with no subpath. Deploy that directory to any static host:

```bash
./bookflow build
npx vercel deploy dist --prod    # or Netlify, GitHub Pages, any static host
```

On a static host the app is read-only: playback, search, transcripts, and
playlists all work, with playlists kept in the browser's own storage rather
than `data/playlists.json`. Regenerate and redeploy `dist/` after adding
books or audio.

## Structure

- `book.json`: identity, editions, discovery, research sources, and coverage.
- `content.json`: the canonical argument, ideas, book map, rating, reading experience, critique, audience, and decision.
- `scripts/*.md`: audio-ready presentations derived from the structured content.
- `library/authors/<author-id>/author.json`: sourced author profiles behind the app's author pages.
- `data/relationships.json`: traversable links between books and authors.
- `taxonomy/tags.json`: controlled discovery terms.

Books are processed from `data/queue.json` in priority order: `./bookflow queue` shows what each book still needs, and `./bookflow next` hands an agent the next ready book with its research prompt. Coverage (`sample-and-secondary` versus `full-book`) is recorded on every profile as plain metadata — it never blocks a brief from being written, it just tells you how it was researched.
