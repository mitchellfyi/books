# Research basis for length and presentation

This note records why the product works as it does. It is not a second set of
agent instructions. `config/audio.json` owns duration and word-count values;
`AGENTS.md` owns the workflow; the schemas own field structure.

## Product decision

There is no proven universal length for a non-fiction book or summary. The
reader's task, prior knowledge and the book's density all change what is
enough. This product therefore uses progressive depth:

- thirty seconds as a discovery card for search and browsing;
- five minutes for one useful idea and a read, buy or skip decision;
- fifteen minutes as the default useful account of a whole book;
- thirty minutes only when fifteen would lose necessary reasoning, evidence,
  dispute or structure;
- no routine ninety-minute brief, because it no longer protects the reader
  from a book-sized time commitment.

These are product boundaries, not biological attention limits. The exact
configured levels and targets are in `config/audio.json`. Choose the shortest
level that passes the loss test in `AGENTS.md`; never pad to reach a duration.

## Evidence and consequences

| Evidence | What it means here |
| --- | --- |
| A [meta-analysis of 190 studies](https://biblio.ugent.be/publication/8647789) estimated adult silent non-fiction reading at 238 words per minute and oral reading at 183, with wide individual variation. | Time labels are estimates. Calculate them from the current word targets and playback rate rather than copying derived values into content. |
| An [edX study of 6.9 million viewing sessions](https://up.csail.mit.edu/other-pubs/las2014-pguo-engagement.pdf) found shorter instructional videos more engaging and recommended very short segments. It treated engagement as necessary but insufficient for learning. | The five-minute level is a useful idea-sized or decision-sized unit, not proof that every book can be understood in five minutes. Longer audio needs semantic chapters. |
| A [meta-analysis of 56 segmentation investigations](https://doi.org/10.1007/s10648-018-9456-4) found small-to-medium gains in retention and transfer, but no universal best segment length. | Divide material at meaningful boundaries and give the listener control. Do not split it by an arbitrary timer. |
| A review of the common [ten-to-fifteen-minute attention-span claim](https://doi.org/10.1152/advan.00109.2016) found no sound evidence for a fixed limit. | Judge length by information loss and user purpose, not an attention-span myth. |
| [Jellybooks' instrumented ebook data](https://www.jellybooks.com/about/jellybooks-radar/completion-rate) shows uneven completion, while its founder warns that completion is less meaningful for [non-fiction read selectively or deferred](https://janefriedman.com/reader-analytics-jellybooks/). | Support non-linear entry points. Do not use completion alone as a measure of value. |
| A [Pew analysis of 451 top-ranked podcasts](https://www.pewresearch.org/journalism/2023/06/15/podcast-format/) found many successful episodes between 20 and 50 minutes or longer. | There is no defensible podcast-duration cliff from which to derive the book-brief limit. |
| Research on [web reading](https://www.nngroup.com/articles/how-users-read-on-the-web/) and [progressive disclosure](https://www.nngroup.com/articles/progressive-disclosure/), plus [GOV.UK content guidance](https://guidance.publishing.service.gov.uk/writing-to-gov-uk-standards/writing-guidelines/meet-user-needs/), supports concise, front-loaded and task-focused presentation. | Show the verdict and core argument first. Reveal structured detail on request. Use descriptive headings, plain language and one idea per paragraph. |
| Reviews of learning methods rate [retrieval practice and distributed practice](https://doi.org/10.1177/1529100612453266) more generally useful than passive summarisation; [retrieval practice also beat concept mapping](https://pubmed.ncbi.nlm.nih.gov/21252317/) in a controlled experiment. | A brief is for orientation and decisions. Add optional recall and application prompts when durable learning matters. |
| A [meta-analysis of irrelevant but interesting details](https://doi.org/10.1007/s10648-025-10099-z) found a small overall learning cost. | Keep examples that explain a mechanism or limit. Remove decoration and repeated anecdotes. |
| A [2025 playback-speed meta-analysis](https://doi.org/10.1007/s10648-025-10003-9) found small, often non-significant test costs at 1.5x and below, with costs growing at higher speeds. | Keep narration natural and let listeners control speed. The default is a convenience, not a promise of equal comprehension for every person or topic. |

Commercial summary services clustering around ten to fifteen minutes are weak
market evidence, not learning science. [Blinkist](https://www.blinkist.com/about)
and [getAbstract](https://www.getabstract.com/en/how-it-works) support the
default's plausibility; [Shortform's longer layered guides](https://www.shortform.com/blog/how-to-use-shortform/)
show that deeper study is a separate task.

## Product evaluation

Optimise for a useful decision, not minutes consumed. With the reader's
consent, measure:

- movement from the discovery card to the decision brief;
- completion of the recommended brief;
- requests for a deeper level;
- confidence in `read`, `summary is enough` or `skip`;
- delayed recall of the core argument;
- whether a longer level changes the decision or only repeats information.

A confident stop after five minutes can be success. Use real library behaviour
to revisit the default later, but keep the canonical content model stable so
presentation can change without rewriting the research.
