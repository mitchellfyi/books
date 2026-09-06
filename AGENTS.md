@/Users/m12n/.codex/RTK.md

# 5MinBooks agent guide

## Mission

For application code and deployments, follow `docs/error-tracking.md`.
Preserve the Ops-provisioned GlitchTip browser reporter in the built site.

Build a research-backed library of non-fiction books that helps a reader decide whether to read, listen to, borrow, or buy the original. Protect the reader's time and attention. Explain the useful argument faithfully, show what the full book is like to consume, and say plainly when the summary is enough or the book is unlikely to help.

This is not a contest to produce the most text. Use the shortest treatment that preserves the book's useful distinctions, evidence, examples, limits, and reading experience.

## Editorial contract

- Non-fiction only.
- Use simple, precise British English. Explain necessary technical terms at first use.
- Lead with meaning. Remove throat-clearing, generic praise, filler, and repeated conclusions.
- Do not repeat one explanation across the synopsis, ideas, book map, assessment, and scripts. Each field has a separate job.
- Represent the author's argument before evaluating it. Distinguish what the book says from what reviewers say and what the library infers.
- Preserve conditions and uncertainty. Do not turn a qualified claim into a rule.
- Use one representative example when it reveals how an important idea works or where it fails. Remove decorative anecdotes and repeated examples.
- Be critical when evidence, reasoning, omissions, or delivery warrant it. Do not manufacture balance when the evidence is one-sided.
- Write for the product rather than transcribing. Use exact wording only when it improves accuracy, and cite it.
- Never imply that a partial sample or other summary is the full book.
- Keep research machinery out of narration. Scripts must not mention sources,
  citations, coverage labels, fact-checking, workflow status, provenance,
  production, or how the summary was assembled. Do not announce the brief or
  its running time. Start with the book and finish with a useful idea or clear
  reading decision. Research detail belongs in JSON, never in spoken copy.
- Make narration genuinely engaging: open with the book's most arresting idea
  or story, keep momentum, use vivid concrete examples, vary sentence rhythm,
  and land an ending that stays with the listener. Entertain with the book's
  own material, never with invented colour.

## Source of truth

```text
bookflow                                  CLI: init, queue, next, rate, check, test,
                                          build, serve, audio, pronunciation
config/audio.json                         Lengths, word targets, voices, and TTS defaults
config/pronunciations.json                Verified, language-specific TTS pronunciations
config/rating.json                        Rating rubric (ideas and craft) and weights
data/catalog.json                         Discoverable book and author nodes
data/queue.json                           Work dispatcher: what to process, in what order
data/relationships.json                   Typed connections between nodes
data/playlists.json                       Saved listening playlists (written by the UI)
docs/research-and-content-model.md        Why the levels and fields are what they are
docs/rating-model.md                      Rating rationale, limits, and calibration
docs/review-method.md                     Fact-checking and adversarial review protocol
docs/tts.md                               Local audio and pronunciation workflow
library/authors/<author-id>/author.json   Cited author profile
library/books/<book-id>/book.json         Identity, editions, discovery, sources, coverage
library/books/<book-id>/content.json      Canonical ideas, book map, and assessment
library/books/<book-id>/scripts/*.md      Derived, audio-ready treatments
library/books/<book-id>/audio/            Generated audio and provenance sidecars
schemas/                                  Machine-enforced structure
scripts/                                  check.py and generate_audio.py (run via uv);
                                          narration.py, pronunciation.py and rating.py
                                          are shared modules imported by bookflow
tests/                                    Unit tests and lint for the tooling above
taxonomy/tags.json                        Canonical discovery vocabulary
templates/                                New entity scaffolds
app/                                      Local search, reading, player, and playlist UI
```

`content.json` is the single semantic source for a book. Scripts and the UI are presentations of it. Do not copy the full summary into `book.json`, an extra Markdown summary, or several duration files. Update structured content first, then revise affected scripts.

Use stable lowercase ASCII kebab-case IDs. A book ID identifies the work rather than one edition. Record edition details and ISBNs under `bibliography.editions`. Use canonical tag IDs only. Add a tag only if it will help discovery across books; define it in `taxonomy/tags.json` and do not create synonyms as separate tags.

## What every complete book must answer

Populate the fields for their stated purpose:

- `card`: one-sentence identity and a direct reader verdict.
- `overview.synopsis`: what the book is and covers.
- `overview.core_argument`: the central claim the author is trying to establish.
- `ideas`: each distinct main idea, with a short title, claim, explanation, significance, representative example, and caveat.
- `book_map`: how every substantive part develops the argument from beginning to end. Do not redefine ideas here.
- `reading_experience`: structure, voice, pace, evidence style, example style, repetition, prerequisites, and what sustained reading or listening feels like.
- `assessment.rating`: a sourced, reputation-blind score with confidence and the complete configured dimension breakdown.
- `assessment.meaning`, `lessons`, and `importance`: what the work changes, what is worth retaining or applying, and why it matters.
- `assessment.author_and_purpose`: who wrote it, relevant background and expertise, likely purpose, perspective, and limits. Keep fuller career and bibliography details in the author profile.
- `assessment.evidence_quality`: strengths and weaknesses of the book's support, not the popularity of its conclusion.
- `assessment.reception`: professional, specialist, and reader responses to both content and delivery, including material disagreement.
- `assessment.audience`: who benefits, who will not, the topics covered, and why they matter to those readers.
- `assessment.scope`: what the book is not, what it omits, what is missing or weak, and what is dated or contested.
- `assessment.decision`: when to read the full book, when the brief is enough, when to skip it, and which format best suits its delivery.
- `retention`: a few optional recall and application prompts. A summary helps orientation; it does not by itself guarantee learning.

Connections belong in `data/relationships.json`, not repeated recommendation lists. Give each edge a type, useful rationale, basis, confidence, and evidence references when explicit. Add an uncatalogued book or author as a catalogue stub before linking to it.

For a complete book, normally record three to six distinct outgoing book
connections: the most useful next read, a meaningful contrast, and any work
that deepens, applies, or challenges its argument. Use fewer when the
catalogue has no defensible match; never add a weak edge to meet a count.

## Research standard

Online research is mandatory for every book and author. Search broadly enough to verify identity, understand the argument, find disagreement, assess the author's authority, and describe reception. Use as many sources as add distinct evidence; stop when new results only repeat what is already supported. As a minimum working floor, aim for six useful book sources, three author sources, and two independent reception sources. Important claims should use multiple sources when independent corroboration exists.

Do not ask the owner to OCR a book before exhausting online sources. Use any
lawfully available full text, preview, repository copy, transcript, author
extract, library access, or owner-provided file or OCR. Download and search a
long source when that is the efficient way to cover the book. Do not bypass
paywalls, access controls or digital rights management, and do not use copies
that appear to be unauthorised.

The repository imposes no arbitrary excerpt limit. Product purpose controls
selection: summarise the work, use exact wording only where it improves
accuracy, cite it, and never pad a brief with source text.

Prefer sources in this order, according to the claim:

1. a lawfully accessed full book, its notes and index, or a publisher sample and contents;
2. publisher and library records for edition facts;
3. official author, employer, university, or professional profiles for background;
4. direct interviews for the author's intent and own account;
5. reputable professional reviews;
6. subject specialists or scholarly work for technical claims and evidential criticism;
7. reader aggregates for broad patterns in delivery and appeal;
8. commercial secondary summaries only for discovery or corroboration.

Reject pirated copies, scraped text, unattributed SEO summaries, apparent AI content, spam sites, and retailer blurbs presented as reviews. A source can be authoritative for a narrow fact and still be interested or promotional.

Each source record must include:

- a stable source ID, title, publisher or author, direct URL, type, and access date;
- `independence`: `primary`, `independent`, `interested`, or `community`;
- `quality`: `high`, `medium`, or `limited` for the claim it supports;
- a precise statement of what it supports;
- limitations, bias, conflicts, or coverage boundaries.

Use `research.citations` for metadata fields in `book.json` and `author.json`. Use local `source_ids` on interpretive records in `content.json` and the author profile. Do not duplicate both citation methods for one field. Source IDs in `content.json` resolve against `book.json`.

Set `basis` accurately:

- `explicit`: the source directly states it;
- `synthesis`: it combines or paraphrases supported material;
- `inference`: it is the library's reasoned judgement. The text must make the reasoning understandable.

Do not cite a search-results page or a page that merely mentions the topic. Keep short notes while researching and batch related searches. Verify unstable facts such as roles, review aggregates, and available editions on the day of research.

## Rating model

`config/rating.json` is the sole rubric. Score every configured dimension from
0 to 10 in 0.5-point steps, explain the judgement, and cite the content and
evidence used. Use the anchors consistently across books. Then run:

```bash
./bookflow rate <book-id> --write
```

The command applies the weights and writes the one-decimal total. Never tune
the total by hand. The score judges the book as delivered on the page: the ideas'
explanatory power, support, insight, utility, calibration, and information
efficiency, plus the reading craft of their delivery — clarity, voice,
structure, and the pleasure of sustained reading — scored from documented
reading-experience and reception evidence, not the rater's taste. Do not
reward or punish the author's identity, reputation, credentials, politics,
sales, awards, popularity, aggregate review scores, or the agent's agreement
with the conclusion. Reviews may reveal a claim or a craft judgement worth
checking, but they are not votes.

Set rating confidence separately from quality. Confidence records how fully
the available sources cover the work; limited access lowers confidence, not
the score. Do not claim precision that the evidence cannot support.

## Coverage is recorded, not a gate

The owner's instruction: profiles should be as complete and full as the
sources allow, for personal purchase decisions. Coverage never blocks work:
every configured level may be completed and voiced at any coverage.

`workflow.coverage` stays as plain metadata because it costs nothing and
tells a later agent where deepening would help most:

- `metadata-only`: identity known, analysis not yet written.
- `sample-and-secondary`: built from samples, previews, interviews, reviews,
  and detailed secondary accounts.
- `full-book`: checked against a full copy.

The owner often already owns the physical book; online research substitutes
for scanning it. Use the richest lawfully accessible material you can reach:
the owner's own copies, library ebook lending (Libby), Internet Archive / Open
Library lending, publisher samples, Google Books preview, author-published
excerpts, full-text search tools, and detailed chapter-level secondary
accounts. Record what you actually used.

Two rules survive because they protect the owner, not a policy: never invent
specifics no source supports (a wrong "fact" corrupts the buying decision),
and keep `coverage` truthful so nobody re-researches or over-trusts a
profile by mistake. Coverage limits belong in `workflow` metadata only —
never in the narration or the reader-facing text.

## Length model

`config/audio.json` is the only source for levels, targets, tolerance, playback
speeds and TTS defaults. Do not copy those values into other files or hardcode
them in new code. Treat word targets as ceilings as well as targets. Never pad.

Use the configured decision brief as the maximum normal unit for one coherent
idea. Join several semantic chapters for longer whole-book briefs.

Draft the configured levels, compare adjacent versions, and set
`editorial.recommended_level` to the shortest version whose next level adds no
decision-relevant or understanding-relevant information. Extra causal steps,
technical foundations, competing interpretations or necessary structure are
information; repeated explanation and decoration are not. Record the reason
in `editorial.rationale`.

Each level is independently edited for its job; it is not a mechanical truncation of the longer script. Longer audio uses short semantic sections and clear transitions. Expand ambiguous abbreviations, remove tables and raw URLs, and read difficult sentences aloud. Playback speed belongs to the player. Do not rewrite at 250 words per minute to simulate faster listening.

The research behind these rules, including its limits, is recorded once in
`docs/research-and-content-model.md`.

## Processing queue

`data/queue.json` is the work dispatcher: which books to process, in what
order, and where each stands (`ready`, `in-progress`, `done`, `blocked`).

```bash
./bookflow queue                     # the full queue, ordered, with what each book needs
./bookflow next                      # the next ready book and its research prompt
./bookflow next --claim              # same, and mark it in-progress
./bookflow queue --set <id> done     # update a status
```

Work strictly in priority order unless the owner says otherwise. `init` adds
new books to the end of the queue automatically. Queue status is dispatch
state; the content state stays in each book's own `workflow` fields.

**When the queue has no ready books, refill it by discovery.** Research
outward from the existing library: which books do the catalogued works cite,
answer, or get recommended alongside; what do readers of them read next;
which related titles are demonstrably popular or important. Verify each
candidate with online sources, then `./bookflow init --discovered` it,
record the relationship edges that justify the addition, and let the owner
reorder priorities. Prefer a few well-justified additions over many
speculative ones.

## Workflow

### 1. Initialise

Check the catalogue by title, author, alternate title, and ISBN to prevent duplicates. Then run:

```bash
./bookflow init --title "Book title" --author "Author name"
```

The command refuses titles that normalise to a different existing catalogue
entry (`--force` overrides), promotes a matching recommendation stub when its
ID is supplied, creates the book and author scaffolds and catalogue entries,
then prints a research prompt. It also reports whether the book joined a new
author profile or an existing one: author IDs are derived from the name, so
two different people can collide on one — check before researching into it.
Add the cited written-by relationship during research. The command does not
perform research.

### 2. Research

Resolve the exact work and editions. Gather primary and bibliographic sources first, then author context, independent reception, subject criticism, and reader patterns. Record sources as they are used, including limitations. Acquire or receive lawful full-book access before claiming full coverage.

### 3. Write structured content

Fill in the scaffold `init` created rather than writing these files from
scratch. Field shapes differ between neighbouring fields — some lists hold
sourced claim objects, others plain strings; sources use `accessed_at` and a
closed `type` enum; `selected_works` years are integers — and the templates
already have every shape right. Source IDs used in `content.json` must exist
in that book's `book.json`, even when the claim is about the author.

Complete `book.json`, the author's `author.json`, and `content.json`. Cover the whole book before polishing prose. Consolidate overlapping ideas. Map every content source ID to a recorded source. Label inference. Complete the rating dimensions and let `./bookflow rate <book-id> --write` calculate the total. Choose the recommended duration from the loss caused by compression, not from page count.

### 4. Fact-check and adversarially review

Follow `docs/review-method.md`. Verify basic identity and edition facts, the
book's actual argument, consequential external claims, citation entailment,
and the strongest credible counterevidence. Then review the profile against
the tone, purpose and simple-language standard of 5MinBooks. Inspect and fix
the work rather than only reporting defects. Preserve honest partial status.
Run these passes separately:

1. **Identity:** correct title, author, work, editions, dates, ISBNs, and duplicate detection.
2. **Coverage:** every substantive part represented; full-book claims supported by full-book access.
3. **Evidence:** consequential claims supported; source quality, independence, disagreement, and bias described accurately.
4. **Rating:** every component follows the rubric, cites its evidence, and the calculated total is current.
5. **Compression:** repeated claims and examples removed; fields keep distinct jobs; no important distinction lost.
6. **Reader advocacy:** direct best-for, not-for, missing, read/summary/skip, and format guidance.
7. **Plain language and audio:** clear sentences, necessary terms explained, natural spoken rhythm, target met without padding.

Record material corrections in `workflow.review_notes` or `next_steps`. Do not mark work complete merely because the files are full.
Set `workflow.quality_review` to `passed` only after every check is complete,
the audio pronunciation sample has passed, and the review date and remaining
uncertainties are recorded.

### 5. Derive scripts, choose the length, and generate audio

Draft every configured level from the same `content.json`. Compare adjacent
drafts with the loss test and set `editorial.recommended_level` and its
`rationale`. Every level must be complete even when a longer version adds
context rather than changing the decision. Update scripts after changing
`content.json`, then validate.

Generate audio in listening-priority order — the recommended level first,
then the configured discovery level, then every remaining level. Running
the command without a level does this automatically:

```bash
./bookflow audio <book-id>
```

The first run downloads packages and the Kokoro model into `models/`; after
that, generation is fully local. Only scripts marked `status: complete` are
voiced; unchanged scripts are skipped (`--force` regenerates), and speaking
speed is calibrated to `base_words_per_minute`. Each audio file (MP3 by
default) receives a committed sidecar containing the script hash, engine,
model, voice, speed, measured duration, and pronunciation-dictionary hash;
`check` uses the hashes to flag stale audio. Audio is stored locally under the
book's `audio/` directory, and is committed so the published site can serve it
— commit a book's audio with the book. Do not commit model weights: they are
340 MB and download on demand.

Follow `docs/tts.md` for pronunciation. Generate and listen to the shortest
approved script before marking `audio_pronunciation` passed. Check the author,
title, technical terms, abbreviations and numbers. If Kokoro is wrong, add a
language-specific entry to `config/pronunciations.json` only after verifying
it from a reliable pronunciation source or the person's own speech. Never
guess a phoneme string. Then regenerate the affected audio: a dictionary
change stales only the narrations whose script actually uses a changed term,
so unrelated audio stays fresh and is not re-voiced. Use the shared dictionary rather than
retraining or modifying the model, which keeps every correction reviewable
and repeatable.

### 6. Validate and use the library

```bash
./bookflow check
./bookflow build
./bookflow serve
```

`check` validates schemas, IDs, tags, citations, ratings, content references, relationship endpoints, word counts, coverage labels, and audio freshness. `serve` rebuilds the local data and opens the search, reading, audio, speed, and playlist UI.

A completed book without current local audio is an error: `check` is the gate
on the definition of done, and it must be able to fail. Recordings are not
committed, so anywhere they could not be — a fresh clone, a CI runner —
`./bookflow check --no-local-audio` reports their absence as a warning
instead. Audio whose sidecar disagrees with its script is an error either way,
because that mismatch is committed and travels. Never reach for
`--no-local-audio` to get a book past the gate: generate the audio.

## Agent operating rules

Precision and economy matter as much as correctness. Agents working here:

1. **Do exactly the task.** One book, or the named set, per run. No drive-by
   reformatting, renaming, or restructuring outside the task. Changes to
   shared structure — schemas, templates, `bookflow`, `scripts/`, `app/`,
   this file — are their own task, stated in advance.
2. **Protect concurrent work.** Inspect Git status before editing and do not
   overwrite changes you did not make. Content work on different books can
   run in parallel; coordinate explicit ownership before changing shared
   schemas, tooling, taxonomy, catalogues, relationships, or the app. Extend
   shared code in place.
3. **Check first, work, check last.** Start with `./bookflow check <book-id>`
   to see the true state; hand off only when `./bookflow check` is clean.
   Do not run the full check after every small edit, and do not re-verify
   facts the profile already cites unless something contradicts them.
4. **Never redo settled work.** Do not re-research a recently researched
   profile, regenerate audio that `check` reports fresh, or rewrite scripts
   that meet their targets, unless asked or the content changed.
5. **No surviving TODOs.** Template text may not remain in any file whose
   status claims completion; audio generation refuses scripts containing
   TODO.
6. **Stop instead of improvising.** If sources conflict irreconcilably or
   the schema does not fit the non-fiction work in hand, record the
   situation in `workflow` (and `blocked` in the queue) and stop. Missing
   full-text access is not a stop condition — write the fullest profile the
   available sources support and record the coverage.
7. **Budget research effort.** Batch related searches, keep notes as you go,
   and stop searching when new sources only repeat what is already cited.
   The floors in the research standard are floors, not a checklist to pad.

## Definition of done

A completed book has valid structured files; the fullest treatment its sources allow, with coverage recorded; distinct, sourced ideas; a complete book map; a current reputation-blind rating; clear reading experience, evidence, reception, audience, omissions, and decision advice; a passed adversarial quality review; every configured script within tolerance; checked pronunciation; locally generated current audio for every level; useful graph links; a queue entry marked `done`; and no unresolved validation errors. The text is concise enough to scan, natural enough to hear, and honest enough to trust.

When the owner asks to process the queue and commit the work, commit shared
workflow changes first, then make one focused commit after each completed
book. Never combine a half-finished book with the next one, and do not push
unless the owner asks.

Before handing off any change, run:

```bash
./bookflow check
./bookflow build
```

After changing shared tooling (`bookflow`, `scripts/`, `app/`), also run
`./bookflow test`, which runs the unit tests and then lints the tooling.
Those tests cover the tooling only — none of them asserts anything about a
book, so they stay green while a profile is half-written.

If the directory is a Git repository, also review `git status` and the diff
(`rtk git status --short` and `rtk git diff` when RTK is installed); if it is
not, say so in the handoff instead.
