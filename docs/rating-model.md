# Rating model

The rating estimates the value of a book's content and ideas for an
information-seeking reader. It is not a score for the author, prose, cultural
status, popularity, or likely enjoyment. Those facts can inform the separate
reader decision without changing the rating.

## Why this structure

Open-ended judgement cannot be made fully deterministic. An analytic rubric
makes it more comparable and auditable: a review of 75 studies found that
rubrics can improve scoring reliability, especially when they are analytic
and paired with anchors or rater training, but warned that a rubric does not
create validity by itself ([Jönsson and Svingby,
2007](https://doi.org/10.1016/j.edurev.2007.05.002)). This is why the library
records component scores, rationales, sources, fixed weights, and common
anchors rather than asking for one unexplained number.

Evidence quality and confidence are separate. Cochrane's guidance treats
certainty as a structured judgement involving bias, inconsistency,
indirectness, imprecision, and publication bias, and requires assessors to
justify each judgement ([Cochrane Handbook, Chapter
14](https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-14)).
This library borrows the principles of explicit domains, documented reasons,
and separate confidence; it does not claim to apply GRADE to every kind of
non-fiction.

The dimensions and weights in `config/rating.json` are a product decision for
this library. Evidence and reasoning receive the largest weight because weak
support limits reliance. Explanatory power and insight measure understanding;
utility measures use; completeness checks limits and counterarguments; and
information efficiency protects the reader's time. The last factor judges
avoidable repetition, not literary taste.

## Calculation and calibration

Agents assign every component in half-point steps using the common anchors.
`bookflow` applies the configured weighted mean and rounds half up to one
decimal place. Validation rejects missing dimensions, unknown dimensions,
invalid steps, changed order, weights that do not total one, and stale totals.
Confidence reports source coverage and never changes the score.

The decimal makes close calculations visible; it does not imply laboratory
precision. Improve consistency by periodically rescoring a small, varied
benchmark set without seeing earlier totals and resolving material differences
against the written rationales. Change weights or dimensions only for the
whole library, increment the rubric version, and recalculate every book. Never
adjust the rubric to produce a preferred result for one title.
