@/Users/m12n/.codex/RTK.md

# Book library agent guide

## Purpose

This repository is a research-backed library for deciding whether to read, listen to, borrow, or buy a book. It should let a reader:

- understand a book at several levels of detail;
- judge its relevance, strengths, limitations, and likely value;
- discover connected books, ideas, and authors;
- turn concise, original summaries into spoken audio.

Optimise for accuracy, traceability, clear judgement, and fast scanning. Do not optimise for the number of files or the amount of prose.

## Repository map

```text
config/                         Shared settings, including audio lengths
data/
  catalog.json                  All known book and author nodes
  relationships.json            Typed edges between nodes
library/
  authors/<author-id>/
    author.json                 Cited factual profile and concise synthesis
    profile.md                  Readable author profile
  books/<book-id>/
    book.json                   Cited metadata and concise analysis
    summary.md                  Complete readable book analysis
    scripts/                    Audio-ready scripts by duration
    audio/                      Generated audio; normally ignored by Git
schemas/                        JSON Schemas for maintained JSON files
taxonomy/tags.json              Canonical tags and their definitions
templates/                      Files to copy when adding an entity
```

Use Markdown for prose people will read or narrate. Use JSON for structured facts, source records, tags, workflow state, and graph data. Do not bury long summaries inside JSON strings.

## IDs, paths, and editions

- Use stable, lowercase, ASCII kebab-case IDs: `alchemy-rory-sutherland` and `rory-sutherland`.
- A book ID identifies the work, not a particular edition. Store edition-specific ISBNs and publication details in `book.json`.
- If two books would produce the same ID, append the first publication year.
- Never rename an established ID without updating the catalog, relationships, citations, and inbound links.
- Use British English unless a title or quotation uses another form.

## Required book coverage

Every completed book must answer these questions without repeating the same explanation in several sections:

1. **Synopsis:** What is the book, in a compact paragraph?
2. **Core argument:** What central claim is the author trying to establish?
3. **Main ideas:** What are the distinct ideas? Give each a short title and a precise description.
4. **Whole-book summary:** How does the argument or narrative develop from beginning to end? Cover all substantive parts, not just the premise or opening chapters.
5. **Meaning, lessons, and importance:** What should a reader retain, apply, question, or see differently?
6. **Author and purpose:** Who wrote it, what relevant background and expertise do they have, why was it written, and what else have they written?
7. **Reception:** How did professional reviewers, subject specialists, and readers receive the content and its delivery? Include material praise and criticism.
8. **Audience and topics:** Who is it for, what does it cover, and why might those readers care?
9. **Scope and omissions:** What is it not? What does it not cover? What is missing, weakly supported, dated, or outside its stated scope? Who is unlikely to enjoy or benefit from it?
10. **Connections:** Which books, authors, and ideas should a reader explore next, and why?

For fiction, adapt the same headings: treat the core argument as themes or governing concerns, main ideas as themes/motifs/formal choices, and whole-book summary as a clearly labelled spoiler synopsis.

## Research is mandatory

Browse the web for every new book and author, even if the facts appear familiar. Record the access date. Prefer the most direct and authoritative source available for each claim.

Use a mix of source types:

1. the book itself, a legally accessed copy, publisher-provided sample, table of contents, notes, or index;
2. official publisher and library catalogue records for titles, editions, dates, ISBNs, and subjects;
3. the author's site, employer, university, professional body, or recorded interviews for biography, expertise, intent, and influences;
4. independent professional reviews from reputable publications;
5. subject-matter reviews or scholarly commentary when the book makes technical, historical, scientific, medical, legal, or financial claims;
6. reader aggregates such as Goodreads or StoryGraph for broad reception patterns, never as the sole authority;
7. secondary summaries only as discovery aids or corroboration, not as substitutes for the book.

Research broadly enough to find disagreement. As a working floor, seek at least six useful sources for a book, at least three for an author, and at least two genuinely independent sources for reception. These are minimums, not quotas. Keep adding sources while they contribute a new fact, perspective, correction, or criticism; stop when additional results merely repeat existing material.

Do not use unattributed SEO summaries, scraped copies, AI-generated pages, retailer blurbs presented as reviews, or pirated books as evidence. A publisher page is authoritative for publication facts and marketing positioning, but it is not independent evidence of quality.

If the full book is unavailable, say so in `workflow.coverage_notes`. Do not describe a summary as complete when it is based only on a blurb, sample, interview, or other summary. Mark unsupported areas as incomplete and leave a clear next step.

## Citations and evidence

Facts in `book.json` and `author.json` must be traceable to their `research.sources` entries.

- Give every source a stable local ID such as `publisher-book-page`.
- Store title, publisher or author, URL, source type, access date, and a short note explaining what the source supports.
- Map JSON Pointers to source IDs in `research.citations`. Example:

```json
{
  "/bibliography/first_published": ["publisher-book-page", "worldcat-record"],
  "/profile/career": ["official-employer-bio", "ted-speaker-bio"]
}
```

- Cite important interpretive items locally with `source_ids`, especially main ideas, attributed author intent, criticisms, reception claims, and relationship rationales.
- Use two or more sources for consequential facts when independent corroboration is available.
- Label a statement as `synthesis` when it combines evidence, and as `inference` when it is the agent's reasoned conclusion rather than a source's explicit statement. Explain the inference briefly.
- Do not cite a search-results page. Cite the page that contains the evidence.
- Do not cite a source that merely mentions the topic without supporting the claim.
- Keep direct quotations short and necessary. Prefer an original paraphrase with a citation.

For Markdown, use descriptive inline links or compact source markers that resolve to the profile's source list. A reader should be able to distinguish the author's position, a reviewer's judgement, and the library's synthesis.

## Writing standard

- Lead with the answer. Use short, concrete sentences.
- Do not repeat the synopsis in the core argument, the core argument in every main idea, or the author's biography in the book summary.
- Separate content from evaluation: first explain what the book says, then assess its evidence, delivery, limitations, and usefulness.
- Attribute contested claims. Do not turn the author's opinion into fact.
- Include counterarguments when reputable sources raise them.
- Make uncertainty visible. Use `unknown` or a coverage note instead of guessing.
- Avoid promotional language, generic praise, filler, throat-clearing, and conclusions that add no information.
- Preserve the book's nuance. Do not flatten a conditional argument into an absolute rule.
- Use original wording. Summaries must not reconstruct or replace the book.

## Summary and audio lengths

`config/audio.json` is authoritative. The default narration rate is 150 words per minute, giving these targets:

| Label | Duration | Target words |
| --- | ---: | ---: |
| `30-seconds` | 0.5 min | 75 |
| `3-minutes` | 3 min | 450 |
| `12-minutes` | 12 min | 1,800 |
| `30-minutes` | 30 min | 4,500 |

The original requested counts (125, 750, 3,000, and 7,500) imply 250 words per minute, so they are retained in the config as the `requested-fast` preset. Do not mix rates within a book. State the selected preset in each script's front matter and keep within the configured tolerance.

Each duration has a different job:

- **30 seconds:** identity, core argument, ideal reader, and the most important caveat.
- **3 minutes:** synopsis, main ideas, value, audience, and limitations.
- **12 minutes:** whole-book arc, main ideas with examples, author context, reception, lessons, omissions, and next reads.
- **30 minutes:** detailed whole-book treatment with argument development, examples, counterarguments, reception, practical interpretation, and connections. It must add depth rather than repeat the shorter script.

Audio scripts must sound natural when spoken. Expand ambiguous abbreviations, avoid tables and raw URLs, limit parenthetical asides, and use brief signposts. Run a word count before marking a script complete.

Generated audio belongs under `library/books/<book-id>/audio/`. Use Kokoro as the preferred local, open-weight TTS option when audio generation is requested, but read its current official documentation and licence before installing or updating it. Record the model, voice, language, speed, source script, generation date, and tool version in a sidecar JSON file. Do not commit model weights or large generated audio unless the repository policy later opts in.

## Tags and relationships

Use only canonical IDs from `taxonomy/tags.json`. Add a tag only when it improves discovery across multiple entities. A new tag needs a definition, kind, and any aliases; do not create near-duplicates.

Store relationships as typed edges in `data/relationships.json`, not as free-form related-book lists copied into several profiles. Every edge needs:

- stable source and target entity IDs;
- a canonical relationship type;
- a concise explanation of the useful connection;
- evidence source references when the link is explicit;
- `basis: "inference"` and a rationale when it is a conceptual recommendation;
- a confidence level.

Use `data/catalog.json` for discoverable nodes, including uncatalogued recommendations. An external recommendation may be a stub, but it must have enough identity data to avoid ambiguity.

## Workflow for adding a book

1. Search the catalog by title, author, ISBN, and aliases to prevent duplicates.
2. Copy the book and author templates. Reuse an existing author profile when possible.
3. Resolve the work, editions, and canonical IDs.
4. Gather primary and authoritative sources, then independent reception and criticism.
5. Read the legally available book or full text when provided. Otherwise document the coverage limit.
6. Complete cited JSON profiles before writing long prose.
7. Write `summary.md`, then derive audio scripts from it. Short scripts are independent edits, not mechanically truncated long scripts.
8. Add canonical tags, catalog entries, and meaningful relationship edges.
9. Validate all JSON against its schema, check internal IDs and source references, count script words, and inspect links.
10. Mark the profile complete only when every required section is present, factual claims are cited, reception is balanced, and coverage is honestly labelled.

## Definition of done

A book is complete when:

- the JSON files parse and conform to the current schemas;
- all cited source IDs resolve and all catalogued relationship endpoints exist;
- the full-content summary covers the whole work rather than the marketing premise;
- author background, purpose, reception, audience, topics, omissions, and next-book links are present;
- fact, attributed opinion, synthesis, and inference are distinguishable;
- scripts meet their intended duration and do not repeat themselves internally;
- the prose is concise, original, and suitable for both scanning and narration;
- workflow status and research date are current.

Before finishing, run at least:

```bash
rtk git status --short
jq empty data/*.json taxonomy/*.json library/books/*/*.json library/authors/*/*.json
wc -w library/books/*/scripts/*.md
```

If this directory is not yet a Git repository, skip the Git command and report that fact.
