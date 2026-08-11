# Content ingestion — CFA Program Level I 2027

The application intentionally separates the learning engine from curriculum content.

`curriculum-2027-root.json` is the canonical root manifest for this project. It preserves the labels supplied from the 2027 source bundle (`CFA-27-02-LI-B`) and, where they differ, the corresponding public CFA Institute Level I topic label.

Import bundles can define:

- learning modules under one of the 10 seeded Level I topics
- LOS references
- concepts and prerequisite relationships
- formulas and variable definitions
- questions, difficulty and question type
- source/version references
- `distractorConcepts`, which maps a wrong answer to the misconception it represents
- ordered `assessmentSets` under the `mock-exams` collection

The importer accepts both project labels such as `Corporate Finance`, `Equities`, and `Portfolio Construction` and compatibility/canonical aliases such as `Corporate Issuers`, `Equity Investments`, and `Portfolio Management`.

Use `example-bundle.json` as the normalization target. The `/import` page validates and imports the bundle. A program/source-code mismatch is rejected instead of silently mixing another curriculum year into the 2027 graph.

Only import content that you own or are licensed/authorized to use.
