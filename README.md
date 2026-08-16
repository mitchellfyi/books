# 5MinBooks

A local, research-backed non-fiction library for deciding what to read, listen to, borrow, or buy.

The UI presents each book at progressively deeper levels. The current levels
and targets live in [`config/audio.json`](config/audio.json); their research
basis is in [the content model](docs/research-and-content-model.md).

## Use it

Requirements: Python 3.10 or later and [uv](https://docs.astral.sh/uv/). Audio
generation additionally needs Python 3.10–3.13, which uv provisions on its own
when your default interpreter is newer. The library app has no JavaScript build
step.

```bash
./bookflow check
./bookflow serve
```

Narration audio is not committed — it is reproducible from the scripts — so a
fresh clone has none, and a completed book without its audio is an error:
`check` is the gate on the definition of done. Generate it with
`./bookflow audio --all`, or, where the recordings could not be, run
`./bookflow check --no-local-audio` to report their absence as a warning
instead. Audio whose sidecar disagrees with its script is an error either way:
that mismatch is committed, so it travels.

That makes `check` usable as a build gate. On a machine with the audio, run it
plain; anywhere that only has the repository — a fresh clone, or CI — run:

```bash
./bookflow check --no-local-audio    # exit 1 on any error; warnings never fail
./bookflow test                      # unit tests, then lint
```

`./bookflow test` runs the unit tests for the shared tooling — the CLI, the
validator, the static build, the local server, rating arithmetic, pronunciation
matching and script parsing — then lints it for unused imports and undefined
names. Run it after changing anything in `scripts/` or `bookflow`. It tests the
tooling only: no test asserts anything about the books, so a book mid-edit
cannot fail it.

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

Useful flags: `--voice <id>` picks another configured voice, `--force`
regenerates audio the sidecar says is current, `--allow-draft` voices scripts
not yet marked complete, `--speed <n>` sets the base speed before calibration,
`--no-calibrate` keeps the raw speed instead of matching
`base_words_per_minute`, and `--quantized` uses the smaller int8 model.
`./bookflow serve` takes `--port` and `--no-open`; `./bookflow check` takes
`--quiet`, `--no-local-audio`, and an optional book id to check one book;
`./bookflow init` takes `--book-id`, `--author-id`, `--note`, `--force` and
`--discovered`.

The first run installs the declared Python packages and may download model data. Audio is stored under each book's `audio/` directory; audio and model weights stay local and are not committed. A JSON sidecar records how each file was made: a script change makes that audio stale, and a pronunciation-dictionary change stales only the audio whose script uses an affected term. See [the TTS guide](docs/tts.md) before adding or correcting a pronunciation.

Voices come from `tts.voices` in [`config/audio.json`](config/audio.json), with
`tts.default_voice` used unless `--voice` says otherwise. Each level is voiced
per voice as `<level>.<voice>.<format>` alongside a matching sidecar. The
player's voice selector offers the voices the library has actually recorded,
and hides itself while there is only one; generate a second voice and it
appears.

Inspect the phonemes and any shared-dictionary match for a difficult term:

```bash
./bookflow pronunciation "author name or specialist term"
```

## Deploy to a static host

`./bookflow build` writes `dist/`: a complete, root-layout static site
(`index.html` at the top, data and audio inside), so the app serves from `/`
with no subpath. The page and data are rebuilt every time; audio is synced
rather than recopied, so a rebuild moves only the recordings that changed and
drops any the library no longer produces. Books still at `stub` are left out —
they hold nothing but placeholders. Deploy that directory to any static host:

```bash
./bookflow build
npx vercel deploy dist --prod    # or Netlify, or any static host
```

### GitHub Pages, on every push

[`.github/workflows/deploy.yml`](.github/workflows/deploy.yml) publishes to
<https://mitchellfyi.github.io/books/> whenever `main` moves. It runs
`./bookflow test`, then `./bookflow check --no-local-audio`, and only builds
and deploys if both pass — so a broken tool or an invalid library stops the
deploy rather than shipping.

**The published site has no audio.** Recordings are not committed, so the
runner cannot build them and the site carries transcripts without playback:
search, ratings, briefs, book and author pages and playlists all work, and the
player says how to generate the audio locally. Publishing audio needs one of:
committing it (619 MB, against `commit_generated_audio` in
[`config/audio.json`](config/audio.json)), generating it in the workflow (a
340 MB model and hours per full run), or hosting it separately and pointing the
app at it. Deploying `dist/` from a machine that has the audio — the Vercel
line above — publishes it today.

On a static host the app is read-only: playback, search, transcripts, and
playlists all work, with playlists kept in the browser's own storage rather
than `data/playlists.json`. Regenerate and redeploy `dist/` after adding
books or audio.

## Structure

- `library/books/<book-id>/book.json`: identity, editions, discovery, research sources, and coverage.
- `library/books/<book-id>/content.json`: the canonical argument, ideas, book map, rating, reading experience, critique, audience, and decision.
- `library/books/<book-id>/scripts/*.md`: audio-ready presentations derived from the structured content.
- `library/authors/<author-id>/author.json`: sourced author profiles behind the app's author pages.
- `data/relationships.json`: traversable links between books and authors.
- `taxonomy/tags.json`: controlled discovery terms.

Books are processed from `data/queue.json` in priority order: `./bookflow queue` shows what each book still needs, and `./bookflow next` hands an agent the next ready book with its research prompt. Coverage (`sample-and-secondary` versus `full-book`) is recorded on every profile as plain metadata — it never blocks a brief from being written, it just tells you how it was researched.
