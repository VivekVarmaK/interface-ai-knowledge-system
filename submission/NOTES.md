# Knowledge system submission

## Approach

`solution.py` exports `build()` and the three required methods. It runs entirely
offline using the Python standard library. No API keys, model downloads, network
services, or additional packages are required. The public evaluation file is not
read by the implementation. All answer values are extracted from ingested pages.

Each crawl is stored as a separate full website view. An `as_of` date selects the
last snapshot on or before that date; a date before the first crawl returns an
unconfident answer. Missing pages are removed from the current view rather than
carried forward. Old views remain available for historical questions. Explicit
`as_of` takes precedence over a date mentioned in the question. Natural-language
month/year historical questions select the last observation within that month.
Change queries return dated observations, without claiming the crawl date was
the exact date the website changed.

Markdown tables produce facts keyed by entity, qualifier, and metric. Qualifiers
include term, balance tier, purchase versus refinance, loan amount, and vehicle
model-year range. APY, dividend rate, APR, introductory APR, and minimum deposit
are distinct facts. Equally authoritative, equally dated disagreements produce
an unconfident answer and an unresolved conflict instead of an arbitrary winner.
The parser supports both older tables with a `Term` or `Balance Tier` first column
and newer tables with explicit product labels. Footnote digits are removed from
rates. Future-effective table values are withheld. Explicitly expired offers are
excluded from current fact selection. Source URL, snapshot ID, and supporting
excerpt accompany answers and conflicts.

Source precedence favors the canonical product/rate pages, then other product
pages and fee disclosures, then general pages, dated news, educational articles,
and calculators. Effective dates break ties within an authority level. Current
auto-loan answers use the authoritative model-year table, not overlapping stale
calculator tiers. Mortgage tiers are named individually, and rates and APRs are
labeled separately. Unsupported products and terms return an unconfident answer.

Descriptive questions use an ingest-time inverted index with BM25-style ranking,
heading context, source authority, and dated article metadata. Targeted handlers
cover routing-number attribution, membership eligibility, branch locations and
hours, closures, mobile wallets, student loans, and dated organizational reports.
These handlers select source evidence; they do not contain a lookup table of
practice questions or expected answer values. General branch schedules are
examples from dated branch announcements and do not imply all locations have
identical hours. Named branches require explicit source grounding.

## Conflicts

The report compares like-qualified facts. Distinct terms, balances, jumbo versus
regular certificates, APY versus dividend rate, and purchase versus refinance
are not contradictions. Numerically equal formatting is deduplicated. Auto-loan
conflicts compare overlapping model years with the same term, including cases
where the tier boundaries changed. Every reported resolution cites its evidence.
The report distinguishes historical value changes from concurrent disagreements;
a historical rate change is not necessarily an erroneous website claim.

## Validation

Run from the supplied kit root:

```sh
python3.11 -m unittest discover -s tests -v
python3.11 harness/run_eval.py --submission submission --eval eval/public_eval.jsonl --out results/submission
```

The unmodified starter scored 0.0930 on the public evaluation. The completed
solution scored 0.9643 across 40 public questions on Python 3.11, with zero stale
traps or errors, repeat/paraphrase consistency of 1.0, p95 answer time 0.07 seconds,
and ingestion time 17.3 seconds in the final run. This public score excludes the
conflict pillar because the kit does not include a full-dataset conflict gold
file; hidden accuracy and conflict recall remain unmeasured. See the generated
`results/submission/report.json` and `per_question.jsonl` for details.
The solution passes 27 independent synthetic regression tests for temporal boundaries,
full-snapshot removal, source ranking, overlapping vehicle tiers, explicit
expiration, future dates, balance tiers, unsupported products, deterministic
answers, defensive result copies, and operation without networking.

Two supplied evaluation limitations matter:

- Public question `dup-005` has an empty `must_include` list. Without the optional
  external LLM judge, `score_item()` assigns zero correctness to this non-refusal
  question regardless of the answer. The solution still lists the certificate
  rates. We leave the scorer and evaluation data unchanged.
- The small `harness/selftest` omits its fee page from the second snapshot but
  expects that fee to remain current. This contradicts `contract.py`'s explicit
  full-website snapshot definition. We follow the contract and refuse the missing
  current fee while preserving its historical answer.

The question about Volunteer Time Off "last year" has a reference to 2023 despite
the newest snapshot being in 2026. The answer labels the years in the available
reports and declines to assert an unpublished count for the preceding year.

## Limitations and next steps

This is a deterministic domain-focused baseline, not a general semantic reasoning
engine. English paraphrases outside the recognized vocabulary can be missed, and
the retrieval fallback is extractive. Conflicts are strongest for structured
tables and selected organizational claims; arbitrary narrative contradictions
may be missed. Expiration parsing covers explicit dated phrases, not every legal
promotion condition. Publication and effective dates can be incomplete. A dated
branch announcement is evidence of a published schedule, not proof it remains
unchanged indefinitely.

Future work would broaden synonym/entity extraction, normalize more narrative
facts and cross-page aliases, extend per-claim validity intervals, improve
recognition of narrative ambiguity, and evaluate against separately
authored questions. The current views and index are in memory; durable deployment
would persist versioned facts and indexed evidence with an audit trail.

## Submission and data handling

The interface.ai invitation requests a public GitHub repository containing the
solution code. Publish only the submission code, synthetic tests, and our own
documentation. Exclude the supplied website snapshots and ZIPs, assignment PDF,
API keys, generated answer excerpts, and other event data.

Email the repository URL and the exact commit to review to
`assignments@interface.ai`. The invitation specifies no fixed deadline and
encourages AI-assisted development; the candidate should be able to explain the
implementation and its decisions. Submission by email is a separate step from
publishing the repository.
