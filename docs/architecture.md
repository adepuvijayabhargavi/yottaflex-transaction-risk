# YottaFlex Transaction Risk Monitoring and Analyst Review System

## Architecture and Phase Record

| Item | Value |
|---|---|
| Document status | Phase 1-3 complete; Phase 4 migrations, grants, and MySQL pilot execution complete and awaiting final approval |
| Date | 2026-10-31 |
| Project folder | `C:\Users\ADEPU VIJAYABHARGAVI\OneDrive\Attachments\yottaflex-transaction-risk` |
| Implementation status | Phase 4 complete through pilot generation and verification; Phase 5 not started |
| Next gate | Owner approves Phase 4 results before Phase 5 begins |

---

## 1. Purpose and Scope

This document records:

- The approved challenge requirements.
- The verified local development environment.
- The approved high-level architecture.
- The database isolation and permission model.
- The assumptions and open decisions that must be resolved before implementation.

The target is a working MVP for an internal analyst-facing transaction risk monitoring system. It uses synthetic data, explainable risk scoring, alert and case management, an analyst dashboard, REST APIs, reproducibility checks, and CSV/JSON/SQL exports.

---

## 2. Project Inspection

At the start of Phase 0, the project folder was empty.

- No application files existed.
- No `README`, challenge brief, starter code, or configuration existed.
- No existing files were modified or deleted.
- `docs/` was created only to hold this Phase 0 document.

The official challenge brief was not present in the folder and was not found publicly. The mandatory corrections supplied by the project owner are treated as the authoritative requirements.

---

## 3. Verified Environment

### 3.1 Operating system and shell

| Item | Verified value |
|---|---|
| OS | Windows NT 10.0.26300.0 |
| Shell | PowerShell 5.1.26100.9711 |
| Project path | `C:\Users\ADEPU VIJAYABHARGAVI\OneDrive\Attachments\yottaflex-transaction-risk` |

### 3.2 Python

| Item | Verified value |
|---|---|
| Project interpreter | `.venv\Scripts\python.exe` |
| Python version | 3.13.5 |
| pip version | 26.2.2 |
| Py launcher | `C:\Windows\py.exe`, Python 3.13.5 |

Relevant Python packages installed in the project virtual environment:

| Package | Version |
|---|---|
| Flask | 3.1.3 |
| Flask-SQLAlchemy | 3.1.1 |
| Flask-Migrate | 4.1.0 |
| Flask-Login | 0.6.3 |
| Flask-WTF | 1.3.0 |
| SQLAlchemy | 2.1.6 |
| PyMySQL | 1.2.3 |
| cryptography | 50.0.2 |
| Alembic | 1.20.1 |
| Marshmallow | 3.26.2 |
| Faker | 39.1.0 |
| python-dotenv | 1.2.4 |
| pytest | 9.2.0 |
| Ruff | 0.17.3 |
| Black | 26.10.1 |

`cryptography` is required by PyMySQL for the RSA-encrypted
`caching_sha2_password` authentication path over non-TLS connections. It is
declared in `requirements.txt` as `cryptography>=50.0.2,<51.0`.

### 3.3 MySQL server

| Item | Verified value |
|---|---|
| Installed server | MySQL Server 9.1.0 Community Server |
| Service name | `MySQL91` |
| Service state | Running |
| Start mode | Auto |
| Server executable | `C:\Program Files\MySQL\MySQL Server 9.1\bin\mysqld.exe` |
| Listening port | 3306 |
| Listener process | `mysqld` (PID 5392) |
| Command-line client | `C:\Program Files\MySQL\MySQL Server 9.1\bin\mysql.exe` version 9.1.0 |
| Admin client | `C:\Program Files\MySQL\MySQL Server 9.1\bin\mysqladmin.exe` version 9.1.0 |
| MySQL Shell | Not installed |

**Decision:** Use the installed MySQL 9.1.0 Community Server for the MVP. It is
compatible with the planned schema features and the current SQLAlchemy/PyMySQL
configuration. No MySQL 8 installation is required. No MySQL software was
installed, removed, or reconfigured during this phase.

### 3.4 MySQL clients

| Client | Status |
|---|---|
| MySQL Workbench 8.0 CE | Installed, version 8.0.47 |
| MySQL command-line client | Installed at `C:\Program Files\MySQL\MySQL Server 9.1\bin\mysql.exe`, but not on `PATH` |
| MySQL Shell | Not installed |
| DBeaver | Not detected |
| HeidiSQL | Not detected |
| TablePlus | Not detected |
| DataGrip | Not detected |
| `sqlcmd` | Not detected |

MySQL Workbench can be used as the graphical client. The `mysql.exe` client can be used by full path or by adding its folder to `PATH` later. Changing `PATH` is a system change and requires approval.

### 3.5 Database readiness status

| Item | Status |
|---|---|
| `yottaflex` schema | Verified live; `utf8mb4` / `utf8mb4_0900_ai_ci`; 19 application tables plus `alembic_version` |
| `yottaflex_eval` schema | Verified live; `utf8mb4` / `utf8mb4_0900_ai_ci`; `ground_truth` plus `alembic_version` |
| Database users | All six role accounts authenticate, including read-only `ytf_eval_core` and `ytf_migrator` |
| Python MySQL driver | Verified live through SQLAlchemy 2.1.6 + PyMySQL 1.2.3 |
| `cryptography` | Installed, version 50.0.2 |
| `caching_sha2_password` support | Verified through live `caching_sha2_password` authentication |
| Local `.env` | Configured with all seven role-specific URLs; excluded from version control |
| Grant and isolation verification | Complete; the approved table-level grants were applied and verified with `SHOW GRANTS` and live allow/deny checks |

Live verification confirms both schemas exist and contain the applied
migration tables. All role URLs authenticate. Cross-schema isolation is
confirmed for `ytf_app`, `ytf_risk`, `ytf_generator`, and `ytf_eval_core`;
`ytf_eval` has no core access. The local `.env` contains real credentials and is
never committed; this document contains no credentials or passwords.

---

## 4. Approved Requirements

### 4.1 Mandatory dataset targets

| Entity | Required count |
|---|---:|
| Customers | 5,000 |
| Accounts | 7,000 |
| Transactions | 100,000 |
| Alerts | 1,000 |

The fixed random seed is **20261022**.

Implementation must use a pilot dataset first, then scale to these full targets.

### 4.2 Required risk patterns

| Pattern | Rule code | Expected detection signal |
|---|---|---|
| High transaction velocity | `HIGH_TRANSACTION_VELOCITY` | Too many transactions or too much value in a short window |
| New-device activity | `NEW_DEVICE_ACTIVITY` | Device is new, untrusted, or not previously used by the customer |
| Circular fund transfers | `CIRCULAR_FUND_TRANSFER` | Transfer cycle through multiple accounts within a short window |
| Dormant-account reactivation | `DORMANT_ACCOUNT_REACTIVATION` | Transaction after a long inactivity period or on a dormant account |
| High-value transactions | `HIGH_VALUE_TRANSACTION` | Amount above a fixed or behavioral threshold |
| Repeated transactions | `REPEATED_TRANSACTIONS` | Same account, merchant, and amount repeated within a window |

Supporting rules may be added, but the six required patterns must be implemented and tested.

### 4.3 Required edge-case validations

| Edge case | Required behavior |
|---|---|
| Transaction references a closed account | Reject and record a validation event |
| Negative balance without overdraft | Reject and record a validation event |
| Transfer legs do not reconcile | Reject the transfer group and record a validation event |
| Alert without a triggering transaction | Prevent at database and service layers |
| Case disposition before alert creation | Reject and record a validation event |

### 4.4 Other mandatory requirements

- Complete data dictionary for every entity and field.
- Ground truth stored separately from risk-engine inputs.
- Every alert references its triggering transaction and rule.
- Analyst decisions and status changes preserved as append-only historical records.
- Reproducibility verification using the same seed and dataset checksums.
- CSV, JSON, and SQL seed/export deliverables.
- AI usage and prompt history documentation.
- Optional features are deferred until the required workflow is complete.

### 4.5 Core MVP workflow

1. Generate deterministic synthetic data.
2. Score transactions with explainable rules.
3. Create alerts for qualifying transactions.
4. Let an analyst review alerts.
5. Create and investigate cases.
6. Record notes, decisions, assignments, and status changes historically.
7. Show KPIs and charts on a dashboard.
8. Expose the same workflow through REST APIs.
9. Verify reproducibility and export the dataset.
10. Document setup, architecture, risks, validations, exports, and AI usage.

---

## 5. Approved Architecture

### 5.1 Style

The application uses a layered Flask monolith:

- **Models** represent database tables.
- **Blueprints** group routes.
- **Services** contain business logic.
- **Templates** render HTML with Jinja2 and Bootstrap.
- **Static JavaScript** handles charts and interactive actions.
- **Schemas** validate API input and output.
- **CLI commands** handle seeding, scoring, exports, and verification.

Routes should remain thin: receive request, validate, call a service, return a response.

### 5.2 Main components

| Component | Responsibility |
|---|---|
| Data generator | Creates deterministic synthetic core data and separate ground truth |
| Validation layer | Enforces required edge cases |
| Risk engine | Evaluates configurable rules and stores explainable findings |
| Alert service | Creates and manages alert lifecycle |
| Case service | Manages investigations, notes, decisions, and history |
| Dashboard service | Produces KPIs and chart data |
| Reproducibility service | Computes and compares canonical checksums |
| Export service | Produces CSV, JSON, and SQL deliverables |
| REST API | Exposes the workflow as JSON endpoints |
| Web UI | Provides the analyst dashboard and review screens |

### 5.3 Revised directory layout

```text
yottaflex-transaction-risk/
├── run.py
├── config.py
├── requirements.txt
├── .env.example
├── README.md
├── dataset_profiles/
│   ├── pilot.json
│   └── full.json
├── migrations/
├── migrations_eval/
├── exports/
│   ├── csv/
│   ├── json/
│   └── sql/
├── app/
│   ├── __init__.py
│   ├── extensions.py
│   ├── cli.py
│   ├── models/
│   ├── evaluation/
│   ├── blueprints/
│   ├── services/
│   │   ├── data_generator/
│   │   ├── validation/
│   │   ├── risk_engine/
│   │   ├── reproducibility/
│   │   └── export/
│   ├── schemas/
│   ├── templates/
│   ├── static/
│   └── utils/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── edge_cases/
│   ├── reproducibility/
│   ├── performance/
│   └── fixtures/
└── docs/
    ├── architecture.md
    ├── data-dictionary.md
    ├── migrations.md
    ├── model-indexes.md
    ├── risk-rules.md
    ├── edge-cases.md
    ├── reproducibility.md
    ├── exports.md
    ├── api.md
    ├── testing.md
    ├── ai-usage.md
    └── prompt-history.md
```

### 5.4 Data flow

```text
Pilot/Full profile
    -> synthetic generator
    -> core schema (yottaflex)
    -> risk engine
    -> assessments and findings
    -> alerts
    -> analyst review
    -> cases, notes, decisions, audit history
    -> dashboard and REST API
    -> CSV / JSON / SQL exports
```

Ground truth follows a separate path:

```text
Generator
    -> yottaflex_eval.ground_truth
    -> evaluation and testing only
```

Evaluation reads the two schemas through two separate, read-only connections:

```text
ytf_eval       -> yottaflex_eval.ground_truth
ytf_eval_core  -> yottaflex.transactions
               -> yottaflex.risk_assessments
               -> yottaflex.risk_findings
               -> yottaflex.alerts
```

The evaluation job joins the two result sets in Python. No database user joins
across schemas, and the risk engine must never read the evaluation path.

### 5.5 Ground-truth isolation

- Ground truth is stored in a separate MySQL schema, `yottaflex_eval`.
- The core application and risk engine connect only to `yottaflex`.
- There is no SQLAlchemy relationship or ORM import from the risk engine to ground truth.
- The risk-engine database principal has no privileges on `yottaflex_eval`.
- `ytf_eval` reads only `yottaflex_eval.ground_truth`.
- `ytf_eval_core` reads only the core transactions and risk-output tables listed above.
- The evaluation job uses two separate credentials and connections; it does not use a cross-schema database join.
- Automated tests assert that risk-engine modules do not reference ground-truth models or fields.
- Exports keep ground truth in a separate, clearly labeled deliverable.

### 5.6 Reproducibility and exports

- Fixed seed `20261022`.
- Fixed reference timestamp for generated data rather than runtime `now()`.
- Deterministic random streams and insertion order.
- Canonical checksums keyed by business references.
- Per-table and overall SHA-256 checksums stored in `dataset_runs` and `exports/manifest.json`.
- A verification command regenerates a profile and compares checksums.
- CSV, JSON, and SQL exports are generated from the verified dataset.
- Pilot profile is validated before the full profile.

### 5.7 Deferred optional features

The following are not part of the required workflow and are deferred to the final phase:

- Machine-learning anomaly detection.
- Docker Compose.
- Advanced authentication such as SSO or MFA.
- Notifications and webhooks.
- Background job queue.
- External CSV import.
- OpenAPI/Swagger UI.
- CI pipeline.

---

## 6. Database Design Summary

Planned core entities:

1. `users`
2. `customers`
3. `accounts`
4. `account_status_history`
5. `merchants`
6. `devices`
7. `transfer_groups`
8. `transactions`
9. `risk_rules`
10. `risk_assessments`
11. `risk_findings`
12. `alerts`
13. `cases`
14. `case_alerts`
15. `case_notes`
16. `case_decisions`
17. `audit_events`
18. `dataset_runs`
19. `validation_events`

Evaluation-only entity:

20. `ground_truth` in the `yottaflex_eval` schema.

The model-to-table mapping, table-level constraints, and append-only policy are
maintained in `docs/data-dictionary.md`.

Key integrity rules:

- `alerts.transaction_id` and `alerts.triggering_rule_id` are required.
- Alert, assessment, and finding references must be mutually consistent.
- `risk_assessments(transaction_id, model_version)` is unique. This is a mandatory schema constraint so rerunning the same model version cannot create a second assessment for the same transaction.
- `risk_findings(assessment_id, rule_id)` is unique, so one rule cannot create duplicate findings inside the same assessment.
- `alerts.finding_id` is unique, so one finding cannot create duplicate alerts.
- Account balance must satisfy `balance >= -overdraft_limit`.
- Transactions on closed accounts are rejected.
- Transfer groups must reconcile before being marked `RECONCILED`.
- Case decisions require at least one linked alert and must not predate the earliest linked alert.
- Case decisions and all status changes are append-only history.

---

## 7. Database Isolation and Permissions

### 7.1 Schemas

| Schema | Purpose | Access rule |
|---|---|---|
| `yottaflex` | Core application data, risk inputs, assessments, alerts, cases, audit history | Application, risk engine, generator, migrator, and read-only evaluation core access |
| `yottaflex_eval` | Ground truth and evaluation-only data | Evaluation tooling, generator ground-truth writes, and migrator only |

For local development, both schemas may live on the same MySQL instance. They must still be separate schemas with separate grants.

### 7.2 Database principals

The project owner created both schemas and the five original database users
through MySQL Workbench. `SHOW GRANTS` was then verified live for every
principal. The table below is the **final approved target** privilege model.
`ytf_eval_core` is a new account that must be created after approval; it does
not exist yet. Section 7.6 records the last verified live state and the
commands that are still pending.

| Principal | Schema access | Approved privileges | Purpose |
|---|---|---|---|
| `ytf_migrator` | `yottaflex`, `yottaflex_eval` | SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX, REFERENCES on both schemas | Schema migrations and the Alembic version table |
| `ytf_generator` | `yottaflex`, `yottaflex_eval` | CRUD on approved synthetic source tables; `SELECT, INSERT, DELETE` on `account_status_history`; CRUD on `yottaflex_eval.ground_truth` | Seeding and resetting synthetic data and ground truth only |
| `ytf_app` | `yottaflex` | SELECT, INSERT, UPDATE, DELETE | Web application and REST API |
| `ytf_risk` | `yottaflex` | SELECT on approved risk-input tables; `SELECT, INSERT` on `risk_assessments`, `risk_findings`, and `alerts` | Risk scoring, duplicate checks, and result writes |
| `ytf_eval` | `yottaflex_eval` | SELECT on `ground_truth` | Read ground truth only |
| `ytf_eval_core` | `yottaflex` | SELECT on `transactions`, `risk_assessments`, `risk_findings`, and `alerts` | Read core risk results for evaluation only |
| `ytf_readonly` | `yottaflex` | SELECT | Optional reporting and demo read-only access; not created and not required |

Explicit rules:

- `ytf_app`, `ytf_risk`, and `ytf_eval_core` have **no** privileges on `yottaflex_eval`.
- `ytf_eval` has **no** privileges on `yottaflex`.
- `ytf_risk` has no `UPDATE` or `DELETE` on `risk_assessments`, `risk_findings`, or `alerts`.
- `ytf_generator` has no privileges on `validation_events`, `alerts`, `users`, `cases`, `case_notes`, `case_decisions`, `case_alerts`, or `audit_events`.
- `ytf_eval` and `ytf_eval_core` are separate read-only accounts. The evaluation job joins their results in Python.
- `ytf_migrator` is never used by the running web application.
- `ytf_generator` is used only by CLI seed/reset commands.
- No principal receives global `ALL PRIVILEGES`.
- DDL is performed only by the migration principal.
- Application runtime users cannot drop tables or alter schemas.

Detailed final table privileges:

| Principal | Schema and objects | Privileges |
|---|---|---|
| `ytf_app` | `yottaflex.*` | SELECT, INSERT, UPDATE, DELETE |
| `ytf_risk` | `yottaflex.customers`, `accounts`, `account_status_history`, `merchants`, `devices`, `transfer_groups`, `transactions`, `risk_rules` | SELECT |
| `ytf_risk` | `yottaflex.risk_assessments`, `risk_findings`, `alerts` | SELECT, INSERT |
| `ytf_generator` | `yottaflex.customers`, `accounts`, `merchants`, `devices`, `transfer_groups`, `transactions`, `risk_rules`, `dataset_runs` | SELECT, INSERT, UPDATE, DELETE |
| `ytf_generator` | `yottaflex.account_status_history` | SELECT, INSERT, DELETE |
| `ytf_generator` | `yottaflex_eval.ground_truth` | SELECT, INSERT, UPDATE, DELETE |
| `ytf_eval` | `yottaflex_eval.ground_truth` | SELECT |
| `ytf_eval_core` | `yottaflex.transactions`, `risk_assessments`, `risk_findings`, `alerts` | SELECT |
| `ytf_migrator` | `yottaflex.*`, `yottaflex_eval.*` | SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX, REFERENCES |

The generator receives no privileges on `validation_events`, `alerts`, `users`,
`cases`, `case_notes`, `case_decisions`, `case_alerts`, or `audit_events`.
Validation events are written by the validation layer, not the generator.
Alerts are written by the risk engine, not the generator.

### 7.3 Connection configuration

The application uses separate role-specific environment variables:

- `YTF_APP_DATABASE_URL` for the web application and REST API.
- `YTF_RISK_DATABASE_URL` for the risk engine.
- `YTF_EVAL_DATABASE_URL` for the evaluation ground-truth connection.
- `YTF_EVAL_CORE_DATABASE_URL` for the evaluation core-results connection.
- `YTF_GENERATOR_DATABASE_URL` for synthetic-data generation.
- `YTF_MIGRATION_DATABASE_URL` for core migrations.
- `YTF_EVAL_MIGRATION_DATABASE_URL` for evaluation migrations.
- `YTF_SECRET_KEY` for Flask session signing.

No real credentials will be written into the repository. Passwords are supplied
locally through environment variables or a local `.env` file that is excluded
from version control. `.env.example` contains placeholders only.

The local `.env` is configured with real local credentials for all seven role
URLs. It remains excluded from version control. Credentials are not recorded in
this document, in `.env.example`, or in any tracked file.

### 7.4 Enforcement layers

Ground-truth isolation is enforced at four levels:

1. **Schema separation** — `yottaflex` versus `yottaflex_eval`.
2. **Database grants** — application, risk engine, and `ytf_eval_core` have no eval access; `ytf_eval` has no core access.
3. **Application architecture** — no ORM relationship or import from risk engine to evaluation.
4. **Separate evaluation connections** — ground truth and core results are read through two independently scoped accounts and joined in Python.
5. **Tests** — automated checks for forbidden references and schema boundaries.

### 7.5 MySQL version compatibility

The installed server is MySQL 9.1.0 Community Server. It is the selected server
for the MVP, and no MySQL 8 installation is required.

The planned schema uses supported MySQL features:

- InnoDB
- `utf8mb4`
- `JSON`
- `CHECK` constraints
- Foreign keys
- `DATETIME(6)`
- `DECIMAL`
- `ENUM`
- Generated columns
- Composite indexes

The project uses SQLAlchemy 2.1.6, PyMySQL 1.2.3, and cryptography 50.0.2.
SQLAlchemy's MySQL dialect loads with the PyMySQL driver, and cryptography
enables PyMySQL's `caching_sha2_password` RSA authentication path over non-TLS
connections. Live Python authentication succeeded for every role that has
schema privileges.

### 7.6 Grant verification and execution status

Access was verified live against MySQL 9.1.0. On 2026-10-30, the owner
authorized the safe-before-migrations blocks for `ytf_app` and `ytf_migrator`.
After the migrations were applied, the remaining approved table-level grants
were executed on 2026-10-31 through the MySQL administrator connection. No
existing password was changed.

| Principal | Final verified state | Status |
|---|---|---|
| `ytf_app` | Global USAGE; CRUD on `yottaflex.*`; no eval privilege | **Complete.** Verified with `SHOW GRANTS` and live denial. |
| `ytf_risk` | SELECT on eight risk-input tables; `SELECT, INSERT` on assessments, findings, and alerts; no eval access | **Complete.** Schema-level grant removed; table grants applied. |
| `ytf_eval` | SELECT on `yottaflex_eval.ground_truth` only; no core access or writes | **Complete.** Schema CRUD revoked; live denial verified. |
| `ytf_eval_core` | SELECT on `yottaflex.transactions`, `risk_assessments`, `risk_findings`, and `alerts`; no eval access or writes | **Complete.** Account created; grants applied; live denial verified. |
| `ytf_generator` | CRUD on the eight approved synthetic source tables; `SELECT, INSERT, DELETE` on `account_status_history`; CRUD on `ground_truth`; no access to `alerts`, `users`, `validation_events`, or eval tables other than `ground_truth` | **Complete.** Table grants applied; live denial verified. |
| `ytf_migrator` | Global USAGE; SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX, REFERENCES on both schemas | **Complete.** Verified with `SHOW GRANTS`; `ALL PRIVILEGES` removed. |
| `ytf_readonly` | Does not exist | Not required. |

All approved permission corrections are complete:

| Command group | Executed? | Result |
|---|---|---|
| Normalize `ytf_app` | **Yes — verified** | Complete |
| Narrow `ytf_migrator` | **Yes — verified** | Complete |
| Create `ytf_eval_core` | **Yes — verified** | Complete |
| Grant `ytf_risk` | **Yes — verified** | Complete |
| Grant `ytf_generator` | **Yes — verified** | Complete |
| Narrow `ytf_eval` | **Yes — verified** | Complete |
| Grant `ytf_eval_core` | **Yes — verified** | Complete |

MySQL 9.1 rejects comma-separated multi-table `GRANT` statements, so each
table-level grant was issued separately. Live checks confirmed allowed reads
and denied cross-schema or write operations for every role. `ytf_app`,
`ytf_risk`, `ytf_generator`, and `ytf_eval_core` have no evaluation access;
`ytf_eval` has no core access and cannot write ground truth. No credentials or
password hashes are recorded in this document.

### 7.7 Evaluation isolation design

Evaluation uses two independent, read-only connections:

- `ytf_eval` reads `yottaflex_eval.ground_truth`.
- `ytf_eval_core` reads `yottaflex.transactions`, `yottaflex.risk_assessments`,
  `yottaflex.risk_findings`, and `yottaflex.alerts`.

The evaluation job loads both result sets and joins them in Python using the
transaction reference. It does not use a cross-schema SQL join. `ytf_risk` never
receives evaluation credentials and has no privileges on `yottaflex_eval`.

The environment variable for the second connection is
`YTF_EVAL_CORE_DATABASE_URL`. `DatabaseRole.EVAL_CORE` and its URL helper live
in `app/database.py`, with tests proving the evaluation URLs stay separate. The
account exists and the pilot verification uses it as a separate read-only
session for result counts. The evaluation job itself remains a later-phase
deliverable.

### 7.8 Rerun and duplicate prevention

The approved uniqueness definition is one assessment per transaction and model
version. The database constraints are:

- `risk_assessments`: unique `(transaction_id, model_version)`.
- `risk_findings`: unique `(assessment_id, rule_id)`.
- `alerts`: unique `finding_id`, plus a unique alert reference.

Consequences:

- Repeating the same model version for the same transaction cannot insert a
  duplicate assessment. The second insert fails with a duplicate-key error.
- A finding cannot be repeated inside the same assessment for the same rule.
- One finding cannot produce more than one alert.
- The risk engine must use a stable model version for a rerun, check for an
  existing assessment before scoring, and treat a duplicate-key error as
  "already exists" rather than retrying blindly.
- Because `ytf_risk` has no `UPDATE` or `DELETE`, an existing result must be
  reused or skipped, not modified in place.
- A deliberate `model_version` change creates a new assessment by design. It is
  a new result, not a duplicate under the approved uniqueness rule.

The risk-engine rerun logic and its tests are not implemented yet. They are
later implementation work. The schema constraints are mandatory and are now part
of the metadata and test expectations.

---

## 8. Assumptions

1. The mandatory corrections are the authoritative requirements because no official brief file is available.
2. Python 3.13.5 is acceptable for the MVP.
3. The MVP supports 2-decimal currencies only: USD, EUR, GBP, INR, AED.
4. Basic session authentication is included because the analyst workflow requires login.
5. Advanced authentication, ML, Docker, and notifications are optional and deferred.
6. The full 100,000-transaction dataset and exports may be generated on demand; only a small sample may be committed.
7. MySQL Workbench is the graphical client.
8. The MySQL command-line client can be invoked by full path unless the user approves a `PATH` change.
9. Synthetic data contains no real customer PII.
10. No real database passwords or API keys will be requested in chat, exposed in documentation, or committed to tracked project files. Local credentials live only in the version-control-excluded `.env`.
11. MySQL 9.1.0 is accepted for the MVP; MySQL 8 is not required.
12. `cryptography` is a required PyMySQL authentication dependency for local MySQL connections.

---

## 9. Open Decisions and Remaining Work

| # | Decision | Why it matters | Status |
|---:|---|---|---|
| 1 | Use MySQL 9.1 or install MySQL 8 | MySQL version compatibility | **Resolved:** use MySQL 9.1.0 |
| 2 | Create the two schemas and database principals | Needed before migrations | **Resolved:** both schemas and all five original principals verified live |
| 3 | Install project dependencies | Required to run the application and tests | **Resolved:** dependencies installed in `.venv` |
| 4 | Add MySQL `bin` to `PATH` | Convenience only | **Resolved:** use the full client path; no `PATH` change |
| 5 | Provide the official brief if one exists | Ensures no hidden requirement is missed | Awaiting owner input if a brief exists |
| 6 | Replace `.env` placeholders and verify grants | Enables Python connectivity and proves schema isolation | **Resolved:** `.env` configured; grants and isolation verified |
| 7 | Approve the final permission matrix and evaluation isolation | Risk, generator, eval, and migrator grants do not yet match the target model | **Resolved:** matrix approved; all safe-before-migrations and deferred table grants applied and verified. |
| 8 | Make the assessment rerun constraint mandatory | Prevents duplicate assessments for the same transaction and model version | **Resolved:** unique constraint added to model metadata and tests; it must appear in the first core migration |
| 9 | Add `ytf_eval_core` role URL support | Enables ground truth and core results to be read without cross-schema credentials | **Resolved:** `DatabaseRole.EVAL_CORE`, URL helper, template placeholder, and tests added |
| 10 | Create `ytf_eval_core`, configure its real URL, and implement the second evaluation connection | Enables ground truth and core results to be read without cross-schema credentials | **Resolved:** account and URL configured; pilot verification uses a separate read-only result session |
| 11 | Implement and test risk-engine rerun/idempotency logic | Schema constraints prevent duplicates, but the engine must check existing rows and handle duplicate-key errors | **Pending** later implementation |
| 12 | Approve Phase 1 | Formal gate before implementation | **Resolved:** owner approved Phase 1 foundation work on 2026-10-30 |
| 13 | Complete Phase 2 models and schema definitions | Required before any migration can be generated | **Resolved:** 20 models, constraints, indexes, relationships, append-only protection, schema tests, and mapping documentation completed |
| 14 | Approve Phase 2 | Formal gate before migration work | **Resolved:** owner approved Phase 2 on 2026-10-30; migrations await a separate approval |

No passwords should be sent in chat. Real credentials exist only in the local,
version-control-excluded `.env` file. This document and `.env.example` contain
no real credentials.

---

## 10. Phase 0 Checklist

- [x] Inspect the project folder.
- [x] Confirm no existing files were deleted.
- [x] Verify Python version.
- [x] Verify pip version.
- [x] Check relevant installed Python packages.
- [x] Verify MySQL server installation and version.
- [x] Verify MySQL service state.
- [x] Verify MySQL listening port.
- [x] Verify MySQL command-line client.
- [x] Verify MySQL Workbench.
- [x] Check for other MySQL clients.
- [x] Confirm no MySQL software was installed, removed, or modified.
- [x] Confirm no real credentials were requested in chat or written to tracked files.
- [x] Add and install the `cryptography` authentication dependency.
- [x] Verify PyMySQL `caching_sha2_password` support.
- [x] Resolve the MySQL 9.1 versus MySQL 8 decision.
- [x] Record owner confirmation that schemas and users were created.
- [x] Document requirements, architecture, assumptions, and database isolation.
- [x] Replace placeholder values in the local `.env`.
- [x] Verify MySQL authentication through SQLAlchemy/PyMySQL.
- [x] Verify database grants with `SHOW GRANTS`.
- [x] Verify cross-schema isolation for the application, risk, and evaluation roles.
- [x] Verify both schemas, their charset/collation, and that they are empty.
- [x] Run the automated test suite (`57 passed`).
- [x] Run Ruff (`All checks passed`) and Black (`53 files unchanged`).
- [x] Document the final approved permission matrix and evaluation isolation design.
- [x] Add the mandatory `risk_assessments(transaction_id, model_version)` unique constraint to the Phase 2 schema metadata and tests.
- [x] Confirm the existing schema uniqueness rules for findings and alerts.
- [x] Execute the safe-before-migrations SQL with the MySQL administrator connection.
- [x] Verify `ytf_app` and `ytf_migrator` with `SHOW GRANTS`.
- [x] Owner approved Phase 1 foundation work on 2026-10-30.
- [x] Owner approved Phase 2 model and schema definitions on 2026-10-30.
- [x] Implement Phase 3 validation services for core entities and cross-table rules.
- [x] Enforce all five required edge-case validations and record validation events.
- [x] Add valid, invalid, and edge-case validation tests using the SQLite fixture.
- [x] Run the Phase 3 suite (`87 passed`), Ruff, and Black.
- [x] Document validation rules in `docs/validation.md`.
- [ ] Execute the deferred table-level grants after migrations.
- [ ] Owner approval to apply migrations and create tables.

---

## 11. Phase 1, Phase 2, and Phase 3 Gate

**Current status:** Phase 0, Phase 1 foundation, Phase 2 model/schema
definitions, and Phase 3 validation services are complete. The approved
safe-before-migrations grants for `ytf_app` and `ytf_migrator` were executed and
verified.

Phase 2 added the core and evaluation SQLAlchemy models, constraints, indexes,
relationships, append-only ORM protection, schema tests, and the model-to-table
mapping. Phase 3 added cross-table validation services, validation-event
recording, and tests for the five required edge cases. No migration was
executed, no MySQL table was created, no data was seeded, no database password
was changed, and no deferred table-level grant was executed.

Migrations, table creation, deferred grants, account creation for
`ytf_eval_core`, synthetic data, and risk-engine behavior remain blocked until
the project owner gives the next approval.

---

## Appendix A — Verification Commands Used

The following read-only verification commands and the authorized
safe-before-migrations grant commands were used during Phase 0.

### Folder inspection

```powershell
Get-Location
Get-ChildItem -Force
Get-ChildItem -Force -Recurse
```

### Python verification

```powershell
Get-Command python, py, python3 -ErrorAction SilentlyContinue
python --version
python -c "import sys; print(sys.executable); print(sys.version)"
python -m pip --version
python -m pip list --format=freeze
```

### MySQL command discovery

```powershell
Get-Command mysql, mysqld, mysqladmin, mysqlworkbench -ErrorAction SilentlyContinue
Get-CimInstance Win32_Service | Where-Object { $_.Name -match 'mysql' -or $_.DisplayName -match 'mysql' }
Get-NetTCPConnection -LocalPort 3306 -State Listen
```

### MySQL binary verification

```powershell
& "C:\Program Files\MySQL\MySQL Server 9.1\bin\mysqld.exe" --version
& "C:\Program Files\MySQL\MySQL Server 9.1\bin\mysql.exe" --version
& "C:\Program Files\MySQL\MySQL Server 9.1\bin\mysqladmin.exe" --version
```

### Installed application discovery

```powershell
Get-ItemProperty HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*
Get-ItemProperty HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*
Get-ChildItem "C:\Program Files\MySQL" -Recurse -Filter "MySQLWorkbench.exe"
```

### Database connection and grant verification

Read-only verification was performed with SQLAlchemy and PyMySQL using the
role-specific URLs from the local `.env`. Passwords were never printed.

```python
from app.database import DatabaseRole, database_url_for_role
from sqlalchemy import create_engine, text

for role in DatabaseRole:
    engine = create_engine(database_url_for_role(role), pool_pre_ping=True)
    with engine.connect() as conn:
        print(conn.execute(text("SELECT VERSION(), CURRENT_USER()")).one())
        print(conn.execute(text("SHOW GRANTS")).all())
        print(conn.execute(text("SHOW TABLES FROM yottaflex")).all())
        print(conn.execute(text("SHOW TABLES FROM yottaflex_eval")).all())
    engine.dispose()
```

Schema inventory was read through `information_schema.SCHEMATA` and
`information_schema.TABLES`.

### Automated checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m black --check .
```

### Safe-before-migrations grants executed

These are the exact authorized statements. They were executed through the
MySQL administrator connection. No table-level grant was executed.

```sql
REVOKE IF EXISTS ALL PRIVILEGES ON `yottaflex`.* FROM 'ytf_app'@'localhost';
REVOKE IF EXISTS ALL PRIVILEGES ON `yottaflex_eval`.* FROM 'ytf_app'@'localhost';

GRANT SELECT, INSERT, UPDATE, DELETE
ON `yottaflex`.*
TO 'ytf_app'@'localhost';

REVOKE IF EXISTS ALL PRIVILEGES ON `yottaflex`.* FROM 'ytf_migrator'@'localhost';
REVOKE IF EXISTS ALL PRIVILEGES ON `yottaflex_eval`.* FROM 'ytf_migrator'@'localhost';

GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX, REFERENCES
ON `yottaflex`.*
TO 'ytf_migrator'@'localhost';

GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX, REFERENCES
ON `yottaflex_eval`.*
TO 'ytf_migrator'@'localhost';
```

Verified results:

| Check | Result |
|---|---|
| `pytest -q` | 57 passed |
| `ruff check .` | All checks passed |
| `black --check .` | 53 files would be left unchanged |
| MySQL version | 9.1.0 |
| Flask development app | Connected through `ytf_app`; both health endpoints returned 200 |
| Schemas | `yottaflex`, `yottaflex_eval`; both `utf8mb4_0900_ai_ci`; both empty |
| Role isolation | `ytf_app`, `ytf_risk`, and `ytf_eval` cannot cross schemas; `ytf_eval_core` is not created yet |
| Safe-before-migrations grants | `ytf_app` and `ytf_migrator` executed and verified with `SHOW GRANTS` |
| Remaining grant deviations | `ytf_generator` has no schema grants; `ytf_risk` has no output SELECT or INSERT; `ytf_eval` is broader than read-only; deferred until Phase 1 |
| Final permission matrix | Documented and approved in sections 7.2, 7.6, and 7.7 |
| Assessment uniqueness | `uq_risk_assessments_transaction_model_version` added to Phase 1 metadata and tested |

No database or user was created, no password was changed, no table or migration
revision was created, and no deferred table-level grant was executed during
Phase 0. The only write operation was the authorized safe-before-migrations
grant correction for `ytf_app` and `ytf_migrator`.
