# AI Assistance and Usage

## Disclosure

AI assistance was used during the development and documentation of YottaFlex
Transaction Risk Monitoring. The retained project record identifies the
assistant as using Copilot SDK in VS Code. Assistance included planning,
scoped implementation, code and security review, test execution, and
documentation.

This disclosure is based on the conversation summaries and project records
available when this document was prepared. It is not a line-by-line authorship
ledger. The available record does not identify which individual lines were
written by the AI assistant or by the project owner, and it does not preserve a
complete transcript of every interaction.

## Human direction and review

The project owner supplied requirements and constraints, requested plans before
some implementation work, and explicitly approved scoped work before it
proceeded. The owner also requested read-only reviews, specified files and
behavior to preserve, and separately authorized staging and commits for
milestones that were committed. Implementation and commit authorization were
treated as separate decisions.

The assistant used repository inspection, tests, linters, format checks, and
diff checks to validate changes where requested and feasible. These automated
checks support review but do not replace owner review or establish that a
feature is correct in every deployment environment. In particular, a local
CI-equivalent run does not establish that GitHub Actions completed successfully
on GitHub.

## Use in this project

The retained records show AI assistance used for:

- Reviewing project structure, requirements, existing models, authentication,
  database boundaries, and Git state before proposing implementation plans.
- Implementing approved features while preserving explicitly identified
  completed phases and limiting changes to the approved scope.
- Reviewing security and behavior, adding or updating regression tests, and
  reporting validation results and limitations.
- Preparing documentation and examining project readiness against documented
  requirements.

The project owner remained responsible for setting requirements, approving
scope, deciding whether proposed changes should proceed, and authorizing
commits.

## Testing and validation evidence

The retained milestone records report use of pytest, Ruff, Black, and
`git diff --check`. Examples include:

- The Phase 6.5 API milestone reported 188 passing tests, with Ruff, Black, and
  `git diff --check` passing after its final authorized fix.
- The Phase 7 export milestone reported 200 passing tests and passing Ruff,
  Black, and `git diff --check`.
- The Phase 8 CI milestone reported 200 passing tests and passing local
  quality checks. The available record did not verify a successful remote
  GitHub Actions run.
- Full-scale data-generation validation used an opt-in test and an isolated
  SQLite database. The reported checks covered 100,000 transactions, 1,000
  positive ground-truth labels, zero generated Alert rows, and matching
  checksums across repeated runs.

These are historical results from their respective milestones, not a claim
that every command passes against every later worktree state. During the
full-scale generation work, the default pytest collection was separately
reported as blocked by two pre-existing untracked integration tests whose
module names collided with tracked unit tests. That limitation was not
reported as a successful full-suite run.

## Privacy and limitations

This document does not reproduce prompts verbatim. The prompt-history document
contains clearly labeled summaries based on retained conversation records and
Git milestones. No credentials, `.env` values, database URLs, keys, or private
personal information are included. Git commit subjects corroborate project
milestones, but do not independently prove who authored a change or what
prompt led to it.
