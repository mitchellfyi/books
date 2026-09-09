# 5MinBooks project brief

Reviewed 9 September 2026 from repository documentation and the owner's
portfolio working agreement. This is orientation, not a live health report.

## Purpose and audience

A static nonfiction library with researched summaries and audio, helping readers understand an idea and decide whether to read the original book.

Readers looking for a concise, trustworthy introduction. Preserve factual sourcing, editorial conventions, audio/text correspondence and the existing book queue and publishing contracts.

## Work and verification

- Local setup: Use `./bookflow` and the README's local setup; Python dependencies are managed through the repository tooling.
- Verification: `./bookflow check` and `./bookflow build` before handoff; `./bookflow test` for tooling changes. Use any fresh-checkout audio exception only as documented, not to bypass missing required assets.
- CI: `verify.yml`: build, running tooling tests, content checks and the static build.
- Start each session with current open issues/PRs, main CI and relevant release
  evidence. Reuse existing work; the issue tracker owns task status.
- Service changes follow the project's documented Ops deployment and recovery
  procedures. Verify affected integrations and deployed revisions when releasing.

## Evidence, cost and next decision

No verified revenue, acquisition, retention or full recurring-cost baseline was
established for this brief. Use dated analytics, error/recovery evidence, bills
and owner observations; keep estimates and missing evidence explicit. Count
shared services once in the portfolio cost view. Prefer smaller maintenance
burdens over new infrastructure or speculative features.

Proposed next experiment, subject to the owner's decision:

Choose one existing summary and draft a clearer route to the original book. Propose a two-hour editorial/reader-journey review, no spend; measure useful onward clicks and return reading. Any affiliate or other commercial offer needs an explicit owner decision.

Review this question in the next weekly Ops issue. The report itself authorizes
no execution. The owner records decisions there and later assigns an agent to
carry out approved work, linking project issues/PRs and verification back to Ops.

## Context and shared agreement

- [README.md](../README.md)
- [AGENTS.md](../AGENTS.md)
- [M12N working agreement](m12n-standards.md): public-safe local snapshot.

Source: Ops `docs/templates/project-agent-standard.md`, revision
`6ff420bbc82af3494606d4e42e736191f1526864`; reviewed 9 September 2026.
Source SHA-256: `d0b44b33a9d1c2b84626518dd9d4a2958ee89e201185bd723ef5572e2fea7d30`.
Local snapshot SHA-256 (after repository formatting): `d0b44b33a9d1c2b84626518dd9d4a2958ee89e201185bd723ef5572e2fea7d30`.
Project-specific instructions remain in `AGENTS.md` and the linked documents.
Update snapshots through reviewed commits; do not load moving remote instructions
at session startup. Revisit this brief when direction, commands or evidence change.
