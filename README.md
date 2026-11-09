# Temporal credit-union knowledge system

An offline Python solution to interface.ai's knowledge-system assignment. It
ingests complete website snapshots, answers current and historical questions with
source citations, and reports conflicting facts with resolution explanations.
Structured fact extraction and deterministic text retrieval run without an LLM,
API keys, external services, or third-party runtime packages.

## Contents

- `submission/solution.py`: grading entry point. `build()` returns an object with
  `ingest(snapshot)`, `answer(question, as_of=None)`, and `conflicts()`.
- `submission/NOTES.md`: approach, evidence, scoring caveats, and limitations.
- `submission/requirements.txt`: no runtime dependencies.
- `tests/test_solution.py`: 27 synthetic regression tests.
- `run_solution.py`: CLI demonstration using your local participant kit.

The supplied website snapshots, assignment PDF, practice questions, scorer,
generated answer excerpts, credentials, and API keys are not distributed here.
Keep the participant kit provided by the organizers outside this repository.
The implementation does not load practice answers.

## Run tests

Use Python 3.11 or later:

```sh
python3.11 -m unittest discover -s tests -v
```

## Run the official evaluator

From the root of the original participant kit, point its unmodified scorer at
this repository's submission folder:

```sh
python3.11 harness/run_eval.py \
  --submission /absolute/path/to/interface-ai-knowledge-system/submission \
  --eval eval/public_eval.jsonl \
  --out results/submission
```

The scorer extracts the supplied snapshot ZIPs on first use. Organizers can use
their own harness, snapshots, and questions with the same submission entry point.

## Ask questions

From this repository, supply the original participant kit's path:

```sh
python3.11 run_solution.py --kit /absolute/path/to/participant-kit \
  --question 'What is the 17-month certificate APY?'

python3.11 run_solution.py --kit /absolute/path/to/participant-kit \
  --question 'What was the 10-month jumbo certificate APY?' --as-of 2026-05-31

python3.11 run_solution.py --kit /absolute/path/to/participant-kit --conflicts
```

Commands ingest the local snapshots and print JSON. Reuse the object returned by
`build()` to ingest once and answer multiple questions in the same process.

## Design

Each full snapshot has a separate in-memory view, preventing future data from
leaking into historical answers. Tables produce facts keyed by product, tier,
term, and metric. APY, dividend rate, APR, introductory APR, and minimum deposit
remain distinct. Canonical rate pages outrank calculators and archived marketing
material. Equally authoritative unresolved disagreements trigger an unconfident
answer. Descriptive questions use an inverted text index with heading context and
source authority. Answers include supporting evidence where available.

## Validation and limits

- 27 synthetic regression tests pass on Python 3.11.
- Public evaluation score: **0.9643**, compared with **0.0930** for the starter.
- No stale-value traps or runtime errors in that run.
- Repeat and public paraphrase consistency: **1.0**.
- Public p95 answer latency: **0.07 seconds**; ingestion: **17.3 seconds**.

These are local measurements. The public kit has no full-data conflict gold file,
so the conflict pillar and hidden-set performance remain unmeasured. An empty
required-token list makes one public question score zero without the optional
external judge. The implementation is domain-focused: unfamiliar paraphrases and
arbitrary narrative contradictions may be missed. See `submission/NOTES.md`.
