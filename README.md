# YottaFlex Transaction Risk Monitoring and Analyst Review System

Phase 1 established the Flask project scaffold, configuration, database extension wiring, and a basic health check. Phase 2 adds the core and evaluation model definitions. Phase 3 adds cross-table validation services and the five required edge-case checks. Phase 4 adds the applied core/evaluation migrations and the deterministic pilot dataset generator, reset, checksum, and verification services.

## Requirements

- Python 3.11+
- MySQL 8 or the locally installed MySQL 9.1 server
- A project-local virtual environment

## Local Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Edit `.env` locally with your own role-specific database settings and a locally generated secret key. Do not commit `.env`. See `docs/migrations.md` for the separate core and evaluation migration commands.

Generate a local secret key with:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

## Run the Application

```powershell
.\.venv\Scripts\python.exe run.py
```

Open:

- `http://127.0.0.1:5000/health`
- `http://127.0.0.1:5000/api/v1/health`
- `http://127.0.0.1:5000/api/v1/csrf-token` (after signing in)

The authenticated Phase 6.5 JSON API provides alert review, read-only
transaction investigation, and case-management endpoints under `/api/v1`.
It uses the existing Flask session, global CSRF protection for mutations, and
the configured application database session. See [docs/api.md](docs/api.md)
for endpoint details, request examples, permissions, and response formats.

## Role-Specific Database URLs

Each process uses only the credential it needs:

| Role | Environment variable |
|---|---|
| Web application | `YTF_APP_DATABASE_URL` |
| Risk engine | `YTF_RISK_DATABASE_URL` |
| Synthetic generator | `YTF_GENERATOR_DATABASE_URL` |
| Evaluation ground truth | `YTF_EVAL_DATABASE_URL` |
| Evaluation core results | `YTF_EVAL_CORE_DATABASE_URL` |
| Core migrations | `YTF_MIGRATION_DATABASE_URL` |
| Evaluation migrations | `YTF_EVAL_MIGRATION_DATABASE_URL` |

The evaluation ground-truth and core-results URLs must remain separate. The web
application and risk engine never receive evaluation credentials.

## Pilot Dataset Commands

Generate the approved pilot dataset (`seed=20261022`) and its isolated ground
truth:

```powershell
.\.venv\Scripts\flask.exe pilot generate --profile pilot --seed 20261022
```

Preview, then confirm, a run reset without deleting versioned risk rules:

```powershell
.\.venv\Scripts\flask.exe pilot reset --profile pilot --seed 20261022 --dry-run
.\.venv\Scripts\flask.exe pilot reset --profile pilot --seed 20261022 --confirm
```

Verify counts, labels, balances, transfer reconciliation, schema isolation, and
stored checksums:

```powershell
.\.venv\Scripts\flask.exe pilot verify --profile pilot --seed 20261022
```

Export a verified run as local CSV, JSON, and SQL files, or select one format
with `--format csv`, `--format json`, or `--format sql`:

```powershell
.\.venv\Scripts\flask.exe pilot export --profile pilot --seed 20261022
```

See [docs/exports.md](docs/exports.md) for the output layout, manifest,
verification behavior, ground-truth separation, and SQL safety requirements.

The generator and reset commands use `YTF_GENERATOR_DATABASE_URL`. Verification
uses the generator URL for source and ground-truth reads and the read-only
`YTF_EVAL_CORE_DATABASE_URL` for result counts. The pilot run creates 20 fraud
labels and zero alerts. Alerts are created only by the Phase 5 risk engine.

## Dashboard and Authentication Settings

The operations dashboard scopes risk and alert metrics to one explicit model
version so mixed evaluation runs do not distort KPIs. Configure it with:

| Variable | Default | Purpose |
|---|---|---|
| `YTF_DASHBOARD_MODEL_VERSION` | `v1.0.1` | Model version shown on the dashboard |
| `YTF_ALERT_THRESHOLD` | `40` | Evaluation threshold displayed in the dashboard |
| `YTF_DATA_REFERENCE_UTC` | `2026-10-30T00:00:00+00:00` | Reference date shown in the UI |
| `YTF_LOGIN_MAX_ATTEMPTS` | `5` | Failed sign-ins allowed inside the window |
| `YTF_LOGIN_WINDOW_SECONDS` | `300` | Rolling failure window in seconds |
| `YTF_LOGIN_LOCKOUT_SECONDS` | `900` | Client lockout duration in seconds |

Sign-out is a CSRF-protected `POST`. Successful sign-ins, failed sign-ins, and
sign-outs append `AUTH_LOGIN_SUCCESS`, `AUTH_LOGIN_FAILED`, and `AUTH_LOGOUT`
audit events without storing passwords or hashes. Login throttling is held in
process memory; multi-worker deployments should enforce an additional shared
limit at the reverse proxy or use a shared backing store.

## Run Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m black --check .
```

GitHub Actions runs the same checks on pushes and pull requests for Python 3.11
and 3.13. The automated suite uses ephemeral SQLite databases and does not
require MySQL credentials. See [docs/testing.md](docs/testing.md) for details.

## Phase Status

Phase 1 foundation, Phase 2 model/schema definitions, Phase 3 validation
services, and the Phase 4 migration/generator implementation are complete. The
core and evaluation migrations are applied (`yottaflex` has 20 tables including
`alembic_version`; `yottaflex_eval` has `ground_truth` and `alembic_version`).
The deterministic generator, safe reset, canonical checksums, and verification
services are implemented and covered by the test suite.

Phase 4 MySQL pilot execution is complete. The
approved table grants were applied, `ytf_eval_core` was created, and isolation
was verified. The pilot generated the approved counts, produced zero alerts,
and reproduced identical checksums after a confirmed reset and regeneration.
The Phase 5 risk engine and Phase 6.2 alert review workflow are implemented.
Alert workflows provide assignment, acknowledgement, close, and dismiss actions
with append-only audit events. Phase 6.3 transaction investigation provides a
read-only transaction detail view, account history, related transactions,
transfer legs, risk findings, and a timeline assembled from recorded events.
The transaction lookup is available at `/transactions/`, transaction detail at
`/transactions/<transaction_id>`, and account history at
`/transactions/accounts/<account_id>`. These views use the application database
session and stored core records only; they do not access evaluation or
ground-truth data or rerun risk assessments. Phase 6.5 adds the authenticated
versioned API for alert review, transaction investigation, and case management
without changing the existing workflows. Phase 6.4 case management uses the
existing case, case-alert, note, decision, and audit tables without a schema
migration.
Analysts see their assigned and unassigned cases, while supervisors and admins
have cross-case oversight; only managers can change priority, escalate, or
close. Alert links are retained as history when unlinked, and each successful
case mutation is audited in the same database transaction.
