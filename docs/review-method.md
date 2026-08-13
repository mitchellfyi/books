# Fact-check and adversarial review method

Use this method before a book is marked complete. The aim is to catch errors
that would waste the reader's time or distort the book, not to collect checks
for their own sake.

## Check by claim type

1. **Identity and metadata.** Verify the exact title, subtitle, author and
   co-author names, first publication, edition, publisher and ISBN against the
   book or publisher record and a library catalogue. Check current roles and
   other changeable facts on the research date. Resolve name variants rather
   than silently choosing one.
2. **What the book says.** Check the synopsis, core argument, ideas, examples
   and book map against the full text, contents, notes or the best available
   primary extracts. A reviewer's paraphrase is not proof that the book makes
   a claim.
3. **Whether a claim is true.** For consequential scientific, medical,
   historical, economic or statistical claims, trace the book's citation to
   the original work and check current specialist evidence. Look for
   corrections, retractions and serious contrary findings. Crossref makes the
   Retraction Watch data available and updates it each working day
   ([Crossref](https://www.crossref.org/documentation/retrieve-metadata/retraction-watch/)).
4. **Judgement and inference.** Test ratings, omissions, audience advice and
   reading recommendations against the recorded evidence. Label inference and
   explain it. Do not turn agreement, dislike or author reputation into an
   evidential judgement.

Spend the most effort on claims that are central, surprising, disputed,
precise, current, high-stakes or likely to change the reader's decision. Check
ordinary metadata quickly but never guess it.

## Adversarial pass

Read the finished profile as if it were confidently wrong. For every central
claim, ask:

- Does each cited source support the exact wording, or only a nearby topic?
- Is the profile reporting the author's argument as fact?
- What is the strongest credible counterexample or competing explanation?
- Has a qualification, failed case, population limit or date been removed?
- Did several apparent sources copy the same original source?
- Would a specialist, the author, or a critical reader identify a material
  omission or unfair framing?

Search laterally for independent evidence and disagreement. Full Fact's
published method likewise starts by defining the exact claim, prefers primary
sources, seeks a wide range of evidence and normally uses at least two sources
for the central claim ([Full Fact](https://fullfact.org/about/how-we-fact-check/)).
The IFCN principles also require source, method and corrections transparency
([IFCN](https://ifcncodeofprinciples.poynter.org/the-commitments)).

Correct the files, sources and derived scripts when a check fails. Do not hide
the failure in review notes. Record a remaining uncertainty only when the
available evidence cannot resolve it.

## Product and language pass

Check the work against the purpose of 5MinBooks:

- The verdict helps a reader decide whether more time or money is justified.
- The brief gives a fair sense of the whole book and what reading it feels
  like, while coverage remains honest.
- Synopsis, ideas, map, assessment and scripts do different jobs without
  repeating the same explanation.
- Criticism is specific and supported, not performative balance.
- Sentences are short, direct and natural when spoken. Necessary technical
  terms are explained once in simple language.
- The shortest recommended level retains every distinction needed for the
  decision.
- Generated audio has been sampled for names, titles, technical terms,
  abbreviations, numbers and awkward pauses; confirmed errors are added to the
  shared pronunciation dictionary and regenerated.

Set every `workflow.quality_review.checks` value only after that pass. A
completed profile requires a dated `passed` review. Use `blocked` when a
material conflict remains unresolved.
