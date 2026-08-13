---
name: process-next-book
description: Process and adversarially fact-check the next ready non-fiction book in this repository from claim through research, structured content, content-only rating, narration, local audio, validation, and queue completion. Use only when the user explicitly asks to run or process the book queue.
---

# Process Next Book

Complete exactly one queued book. Treat `AGENTS.md`, `config/rating.json`, and
`config/audio.json` as the live instructions; do not copy or replace their
rules here.

## Workflow

1. Confirm the current directory contains `AGENTS.md`, `bookflow`, and
   `data/queue.json`. Stop if any are missing: this skill must operate in the
   5MinBooks repository. Read `AGENTS.md` completely, inspect the working tree,
   and preserve unrelated or concurrent changes.
2. Run `./bookflow next --claim`. Process only the book it returns. If none is
   ready, follow the discovery procedure in `AGENTS.md`, initialise the
   strongest well-supported candidate, and claim it.
3. Run `./bookflow check <book-id>` before editing. Use its output and
   `./bookflow queue` to avoid redoing complete, current work.
4. Research online and complete the book and author records to the source and
   coverage standards in `AGENTS.md`. Use broad, claim-appropriate sources,
   keep coverage truthful, and correct existing work rather than merely
   listing its defects.
5. Complete `content.json`, tags, catalogue metadata, and evidenced graph
   relationships. Keep fields distinct, concise, critical, and useful for the
   reader's decision.
6. Read `config/rating.json`. Assess every dimension from the book's content
   and ideas alone, with a source-backed rationale. Exclude author prestige,
   popularity, awards, reception scores, and personal agreement. Record
   coverage uncertainty as confidence; do not alter component scores because
   access was partial. Run `./bookflow rate <book-id> --write` to calculate the
   total. Never choose or hand-edit the total.
7. Read `docs/review-method.md` and run its fact-check and adversarial passes
   separately. Verify identity and edition metadata, fidelity to the book,
   consequential external claims, counterevidence, citation entailment,
   rating discipline, product fit, and simple language. Correct defects in the
   records and scripts. Set the dated quality review to `passed` only when
   every check is true; never use review notes to excuse a known error.
8. Derive the configured narration scripts from `content.json`, compare
   adjacent lengths with the loss test, and set the shortest sufficient
   recommended level. Use `./bookflow audio <book-id>` for local audio; do not
   reproduce its word-count, ordering, freshness, or TTS logic manually. Read
   `docs/tts.md`, listen to the shortest output, and check the title, author,
   technical terms, abbreviations and numbers. Add only verified corrections
   to the shared pronunciation dictionary, then regenerate affected audio.
9. Run `./bookflow check <book-id>`, then `./bookflow check` and
   `./bookflow build`. Fix every in-scope failure. Mark the queue entry `done`
   only when the repository definition of done is met. If genuinely blocked,
   record the reason and set the entry to `blocked` instead of inventing data.

## Handoff

Report the book, score and confidence, recommended listening level, research
coverage, source count, audio generated or skipped, validation results, and
any unresolved limitation. Do not commit or push unless the user asks.
