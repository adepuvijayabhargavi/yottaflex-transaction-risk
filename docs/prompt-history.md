# Prompt History

## How to read this record

The entries below are **reconstructed prompt summaries, not verbatim
prompts**. They are based on the conversation summaries and phase records
available for this project, with Git history used to corroborate committed
milestones. The original wording for every interaction is not available here.
No missing prompt text has been invented.

Commit subjects record repository milestones; they do not prove the exact
prompt, authorship of individual lines, or that a user message was the sole
cause of a change. Where the source record is incomplete, that limitation is
stated explicitly.

## Reconstructed summaries

| Milestone | Reconstructed prompt summary (not verbatim) | Corroborating record |
|---|---|---|
| Phases 0–4 | The retained material does not preserve enough of the original prompts to summarize them reliably. No prompt wording or detailed instruction is reconstructed for these phases. | `d301eae` — Phase 0–4 completed baseline |
| Phase 5 | The retained conversation summaries do not preserve enough original prompt detail for a reliable reconstruction. No prompt wording or detailed instruction is inferred from the commit subject. | `d9bf436` — Complete Phase 5 risk engine and evaluation |
| Phase 6.2 — Alert Management | Reconstructed summary: inspect the project and prepare a plan without editing; after approval, implement Alert Management only, preserve earlier work, run relevant tests, and do not commit or push. | `1b498c8` — Complete Phase 6.1.1 and Phase 6.2 alert management |
| Phase 6.3 — Transaction Investigation | Reconstructed summary: inspect and plan before changes; after approval, implement read-only transaction investigation using application data, preserve authorization and evaluation-data isolation, and validate without committing or pushing. | `7cbd298` — Complete Phase 6.3 transaction investigation |
| Phase 6.4 — Case Management | Reconstructed summary: plan and agree on case-management policies before implementation; reuse existing case tables, preserve role boundaries and append-only history, validate the work, and leave commit/push decisions to the owner. | `54e4a36` — Complete Phase 6.4 case management |
| Phase 6.5 — REST API | Reconstructed summary: plan and implement a versioned API for alerts, transaction investigation, and cases using existing session authentication, CSRF protection, and the application database; preserve existing behavior and verify authorization, validation, and read-only boundaries. A later review requested a narrowly scoped fix for case-state disclosure and regression coverage. | `a86c70e` — Complete Phase 6.5 REST API |
| Phase 7 — Dataset Exports | Reconstructed summary: implement reproducible CSV, JSON, and SQL exports with manifests, checksums, ground-truth separation, and fixed SQL allowlists. A later review required explicit deterministic row ordering and byte-identical exports/checksums when query result order changes. | `7e14545` — Complete Phase 7 reproducible dataset exports |
| Phase 8 — GitHub Actions CI | Reconstructed summary: add automated pytest, Ruff, and Black checks using the SQLite test setup for Python 3.11 and 3.13; avoid application changes, secrets, and unrelated workflow changes, then review the workflow and documentation. | `df8459d` — Add GitHub Actions CI workflow |
| Full-scale data generation | Reconstructed summary: preserve pilot behavior and implement a 100,000-transaction profile with 1,000 positive ground-truth labels across the six existing patterns. The owner clarified that this target means positive labels, not Alert rows; generation must continue to create zero alerts. Validate repeatability, resource use, and isolated SQLite behavior. | `79e1dc5` — Complete full-scale dataset generation |

## Review and approval pattern

The retained interaction history shows repeated requests to inspect or plan
before implementation, explicit approvals for scoped work, separate
read-only final reviews, and separate authorization before selected commits.
The summaries above condense those interactions and are not a complete
transcript or a substitute for the original requirements.

Some project-readiness reviews and proposed follow-up tasks did not themselves
authorize implementation. A commit in the history is evidence that a
repository change was recorded, not evidence that every proposed task was
completed or that a remote CI run succeeded.
