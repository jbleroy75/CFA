# CFA Recall — adaptive CFA Level I learning engine

CFA Recall is a self-hosted study platform designed around **active recall, adaptive practice and spaced repetition**.
The learning engine is separated from curriculum content so the platform can be deployed first and populated later with content you own or are authorized to use.

## Implemented

- Concept-level mastery score with Bayesian-style posterior (`alpha / (alpha + beta)`).
- Evidence weighted by correctness, difficulty, speed and self-assessment.
- `Je savais / J'ai deviné / Je ne savais pas` handling; lucky guesses receive less credit and return sooner.
- Question-level spaced repetition inspired by SM-2.
- Daily adaptive mix: 35% due reviews, 25% recent errors, 25% weak concepts, 15% unseen questions.
- Diagnostic session to initialize mastery.
- Exam mode with topic blueprint, timer, deferred correction and end-of-block debrief.
- Formula Bank plus formula/calculation drills.
- Automatic Error Book with error causes.
- 7/30-day accuracy, speed, coverage, streak, topic mastery, concept mastery and 30-day mastery delta.
- Readiness score and exam-date-driven daily workload.
- Concept/prerequisite graph.
- Distractor-to-concept mapping to detect repeated concept confusions.
- Versioned JSON import pipeline with validation.
- Bookmarks and notes API.


## Curriculum target: CFA Program – Level I 2027

The database is now explicitly versioned for the user-supplied 2027 curriculum root:

- Source/program code: `CFA-27-02-LI-B`
- Quantitative Methods
- Economics
- Corporate Finance
- Financial Statement Analysis
- Equities
- Fixed Income
- Derivatives
- Alternative Investments
- Portfolio Construction
- Ethical and Professional Standards
- `Mock Exams` is modeled separately as an assessment collection, not as an 11th mastery topic.
- The supplied February 2027 LMS root contains **102 curriculum modules** across the 10 subjects.
- Each topic stores its CFA Learning course ID (`2111`–`2120`), expected module count and modules URL.

| Topic | Course ID | Modules |
|---|---:|---:|
| Quantitative Methods | 2111 | 11 |
| Economics | 2112 | 8 |
| Corporate Finance | 2113 | 7 |
| Financial Statement Analysis | 2114 | 12 |
| Equities | 2115 | 12 |
| Fixed Income | 2116 | 19 |
| Derivatives | 2117 | 10 |
| Alternative Investments | 2118 | 7 |
| Portfolio Construction | 2119 | 6 |
| Ethical and Professional Standards | 2120 | 10 |
| **Total** |  | **102** |

The platform tracks three separate progress signals: **corpus coverage** (modules imported), **study completion** (modules marked complete), and **mastery** (what the learner can reliably recall/apply).

Internal slugs remain stable (`quant`, `corporate`, `equity`, etc.) so historical mastery can survive label changes. The importer accepts canonical 2027 labels as well as compatibility aliases such as `Corporate Issuers`, `Equity Investments`, and `Portfolio Management`.

The import validator can pin bundles to:

```json
{
  "program": {
    "slug": "cfa-program-level-i-2027",
    "name": "CFA Program – Level I 2027",
    "sourceCode": "CFA-27-02-LI-B"
  }
}
```

A mismatched curriculum slug/source code is rejected rather than silently mixed into the 2027 knowledge graph.

Mock questions can be grouped into ordered `assessmentSets`, preserving question order and optional sections such as `session-1` / `session-2`. Mock attempts still update concept mastery, but mocks themselves never become a fake subject.

## Knowledge model

`Topic → Learning Module → LOS → Concept → Formula → Question → Source`

Concepts can reference prerequisite concepts. Questions can reference one or more concepts.
Wrong options can optionally declare `distractorConcepts`, enabling structured confusion detection.

## Content ingestion

Open `/import` and upload a normalized JSON bundle. See `content/example-bundle.json`.

Supported metadata includes modules, LOS, concepts, prerequisites, formulas, variables, questions, difficulty, question type, source/version provenance and distractor-concept tags.

> Only import curriculum/question content that you own or are licensed/authorized to use.

## Stack

- Python 3.12 standard library only at runtime
- SQLite in WAL mode
- Responsive vanilla HTML/CSS/JS
- Docker / Docker Compose
- No npm install and no application package registry required

## Docker deployment

```bash
docker compose up -d --build
curl http://127.0.0.1:3000/health
```

To bind a different host port:

```bash
APP_PORT=8080 docker compose up -d --build
```

The SQLite database is stored in the persistent `cfa_data` Docker volume.

## Update

```bash
git pull
docker compose up -d --build
```

## Tests

```bash
make test
```

Current tests cover adaptive allocation, guessed-answer scheduling, mastery evidence weighting, exam-proximity workload, the canonical 2027 root taxonomy, topic aliases, curriculum mismatch rejection, and Mock Exam assessment imports.

## Main routes

- `/` home
- `/curriculum` 2027 root taxonomy and assessment collections
- `/practice` adaptive study
- `/dashboard` analytics
- `/exam` timed exam blocks
- `/formulas` Formula Bank
- `/errors` Error Book
- `/plan` study plan
- `/map` concept/prerequisite/confusion map
- `/settings` exam date and workload
- `/import` curriculum ingestion

## After the full Level I data arrives

The engine itself should not need a rewrite. The main work becomes normalization and enrichment:

1. Map Learning Modules and LOS.
2. Build a fine-grained concept taxonomy.
3. Add prerequisite edges.
4. Extract and map formulas.
5. Map authorized/original questions to concepts.
6. Tag distractors with misconception concepts.
7. Preserve source/version provenance.
8. Calibrate personal difficulty and timing from real attempts.

Once that is loaded, the adaptive engine operates over the complete Level I knowledge graph.
