# Data Dictionary and Model-to-Table Mapping

Phase 2 initially defined the SQLAlchemy models and schema metadata. The
subsequent Phase 4 project record and committed migration revisions document
creation and application of the core and evaluation migrations, followed by
the MySQL pilot. This is historical project evidence; the live MySQL server and
its current schema state have not been freshly checked as part of this
documentation update.

## Conventions

- Core models use `app.models.base.Base` and the `yottaflex` schema.
- Evaluation models use `app.evaluation.base.EvaluationBase` and the
  `yottaflex_eval` schema.
- Evaluation metadata uses the SQLAlchemy bind key `eval`; it is not part of
  the core metadata.
- Every table has a `BIGINT` surrogate primary key named `id`, except that the
  SQLite test variant uses `INTEGER` for autoincrement support.
- Timestamps are UTC `DATETIME(6)` values. Money is `NUMERIC(18, 2)`.
- Enumerated values use Python `StrEnum` classes and validated `VARCHAR`
  columns.
- Foreign keys use `ON DELETE RESTRICT` inside the core schema.
- Tables use InnoDB and `utf8mb4` on MySQL.

## Model-to-Table Map

| Model | Table | Metadata | Purpose | Main relationships |
|---|---|---|---|---|
| `User` | `yottaflex.users` | Core | Analyst, supervisor, and administrator accounts | Audit events |
| `Customer` | `yottaflex.customers` | Core | Bank customer master data | Accounts, devices, transfer groups |
| `Account` | `yottaflex.accounts` | Core | Customer accounts and balances | Customer, status history, debit/credit transactions |
| `AccountStatusHistory` | `yottaflex.account_status_history` | Core | Append-only account status changes | Account, changing user |
| `Merchant` | `yottaflex.merchants` | Core | Merchant master data | Transactions |
| `Device` | `yottaflex.devices` | Core | Customer device fingerprints | Customer, transactions |
| `TransferGroup` | `yottaflex.transfer_groups` | Core | Logical groups of transfer legs | Customer, transactions |
| `Transaction` | `yottaflex.transactions` | Core | Debit, credit, and internal transactions | Accounts, device, merchant, transfer group, assessments, alerts |
| `RiskRule` | `yottaflex.risk_rules` | Core | Versioned risk-rule definitions | Findings, triggering alerts |
| `RiskAssessment` | `yottaflex.risk_assessments` | Core | Aggregate risk result for a transaction | Transaction, findings, alerts |
| `RiskFinding` | `yottaflex.risk_findings` | Core | One rule's explainable finding | Assessment, rule, optional alert |
| `Alert` | `yottaflex.alerts` | Core | Alert raised for a risky transaction | Transaction, assessment, finding, rule, assignee, case links |
| `Case` | `yottaflex.cases` | Core | Analyst investigation grouping alerts | Assignee, opener, closer, case alerts, notes, decisions |
| `CaseAlert` | `yottaflex.case_alerts` | Core | Historical case-to-alert link with soft unlink | Case, alert, linking/unlinking users |
| `CaseNote` | `yottaflex.case_notes` | Core | Append-only investigation note | Case, author |
| `CaseDecision` | `yottaflex.case_decisions` | Core | Append-only analyst disposition | Case, deciding user, triggering alert |
| `AuditEvent` | `yottaflex.audit_events` | Core | Append-only system and analyst audit trail | Optional actor user |
| `DatasetRun` | `yottaflex.dataset_runs` | Core | Reproducible synthetic-data run record | None |
| `ValidationEvent` | `yottaflex.validation_events` | Core | Rejected or flagged data-validity issue | Transaction, resolver |
| `GroundTruth` | `yottaflex_eval.ground_truth` | Evaluation | Fraud labels for generated transactions | None; references use stable string identifiers |

## Column Inventory

| Table | Columns |
|---|---|
| `users` | `id`, `username`, `email`, `password_hash`, `full_name`, `role`, `is_active`, `last_login_at`, `created_at`, `updated_at` |
| `customers` | `id`, `customer_reference`, `first_name`, `last_name`, `email`, `phone`, `country_code`, `risk_segment`, `onboarding_date`, `is_active`, `created_at`, `updated_at` |
| `accounts` | `id`, `account_number`, `customer_id`, `account_type`, `currency`, `status`, `balance`, `overdraft_limit`, `opened_at`, `closed_at`, `created_at`, `updated_at` |
| `account_status_history` | `id`, `account_id`, `previous_status`, `new_status`, `reason`, `changed_by_user_id`, `changed_at` |
| `merchants` | `id`, `merchant_reference`, `name`, `category`, `country_code`, `risk_level`, `is_active`, `created_at`, `updated_at` |
| `devices` | `id`, `device_fingerprint`, `customer_id`, `device_type`, `first_seen_at`, `last_seen_at`, `is_trusted`, `created_at`, `updated_at` |
| `transfer_groups` | `id`, `transfer_reference`, `initiated_by_customer_id`, `status`, `expected_total`, `actual_total`, `currency`, `reconciled_at`, `created_at`, `updated_at` |
| `transactions` | `id`, `transaction_reference`, `transfer_group_id`, `debit_account_id`, `credit_account_id`, `merchant_id`, `device_id`, `transaction_type`, `status`, `amount`, `currency`, `occurred_at`, `description`, `debit_account_status_snapshot`, `credit_account_status_snapshot`, `created_at`, `updated_at` |
| `risk_rules` | `id`, `code`, `version`, `name`, `description`, `category`, `severity`, `score_weight`, `configuration`, `is_active`, `active_code`, `effective_from`, `effective_to`, `created_at`, `updated_at` |
| `risk_assessments` | `id`, `transaction_id`, `model_version`, `score`, `risk_level`, `status`, `assessed_at`, `explanation`, `created_at` |
| `risk_findings` | `id`, `assessment_id`, `rule_id`, `rule_code`, `score`, `severity`, `explanation`, `evidence`, `created_at` |
| `alerts` | `id`, `alert_reference`, `transaction_id`, `assessment_id`, `finding_id`, `triggering_rule_id`, `status`, `priority`, `score`, `summary`, `details`, `assigned_to_user_id`, `acknowledged_at`, `closed_at`, `created_at`, `updated_at` |
| `cases` | `id`, `case_reference`, `title`, `description`, `status`, `priority`, `assigned_to_user_id`, `opened_by_user_id`, `opened_at`, `closed_by_user_id`, `closed_at`, `created_at`, `updated_at` |
| `case_alerts` | `id`, `case_id`, `alert_id`, `linked_by_user_id`, `linked_at`, `unlinked_by_user_id`, `unlinked_at`, `unlink_reason`, `active_alert_id` |
| `case_notes` | `id`, `case_id`, `author_user_id`, `note_type`, `body`, `noted_at`, `created_at` |
| `case_decisions` | `id`, `case_id`, `decided_by_user_id`, `decision`, `rationale`, `decided_at`, `triggering_alert_id` |
| `audit_events` | `id`, `event_type`, `entity_type`, `entity_id`, `actor_user_id`, `summary`, `details`, `request_id`, `occurred_at` |
| `dataset_runs` | `id`, `run_reference`, `profile_name`, `seed`, `status`, `reference_datetime_utc`, `record_counts`, `checksums`, `started_at`, `completed_at`, `error_message` |
| `validation_events` | `id`, `event_reference`, `validation_code`, `severity`, `entity_type`, `entity_id`, `transaction_id`, `message`, `details`, `resolution_status`, `resolution_note`, `resolved_by_user_id`, `resolved_at`, `created_at` |
| `yottaflex_eval.ground_truth` | `id`, `ground_truth_reference`, `dataset_run_reference`, `transaction_reference`, `is_fraud`, `primary_pattern`, `pattern_codes`, `label_source`, `generation_metadata`, `created_at` |

Field types, nullability, Python defaults, and SQL defaults are declared next to
each column in the model modules. This document records the mapping and the
table-level rules that must survive into the migrations.

## Unique Constraints

| Table | Constraint or column rule |
|---|---|
| `users` | `username`, `email` |
| `customers` | `customer_reference`, `email` |
| `accounts` | `account_number` |
| `merchants` | `merchant_reference` |
| `devices` | `device_fingerprint` |
| `transfer_groups` | `transfer_reference` |
| `transactions` | `transaction_reference` |
| `risk_rules` | `uq_risk_rules_code_version` (`code`, `version`) |
| `risk_rules` | `uq_risk_rules_active_code` (`active_code`) |
| `risk_assessments` | `uq_risk_assessments_transaction_model_version` (`transaction_id`, `model_version`) |
| `risk_findings` | `uq_risk_findings_assessment_rule` (`assessment_id`, `rule_id`) |
| `alerts` | `alert_reference` |
| `alerts` | `uq_alerts_finding_id` (`finding_id`) |
| `cases` | `case_reference` |
| `case_alerts` | `uq_case_alerts_active_alert_id` (`active_alert_id`) |
| `dataset_runs` | `run_reference` |
| `validation_events` | `event_reference` |
| `ground_truth` | `uq_ground_truth_reference` (`ground_truth_reference`) |
| `ground_truth` | `uq_ground_truth_run_transaction` (`dataset_run_reference`, `transaction_reference`) |

## Check Constraints

| Table | Rules |
|---|---|
| `accounts` | Non-negative overdraft; balance within overdraft; closed timestamp matches status; close time not before open time |
| `account_status_history` | Previous and new status must differ |
| `devices` | Last-seen time not before first-seen time |
| `transfer_groups` | Non-negative totals; reconciled status has a timestamp; reconciled totals match |
| `transactions` | Positive amount; account fields match transaction type; each used account has a non-closed status snapshot |
| `risk_rules` | Positive version; score weight from 0 to 100; valid effective window |
| `risk_assessments` | Score from 0 to 100 |
| `risk_findings` | Score from 0 to 100 |
| `alerts` | Score from 0 to 100; acknowledgement/close times valid |
| `cases` | Close time not before open time; closed timestamp matches status |
| `case_alerts` | Unlink time not before link time; unlink requires actor and non-blank reason |
| `dataset_runs` | Completion time not before start time |
| `validation_events` | Resolution time not before creation time |
| `ground_truth` | References are non-blank; primary pattern is present only for fraud labels; pattern codes is a JSON array |

Composite indexes and deliberately omitted indexes are recorded in
`docs/model-indexes.md`.

## Append-Only History

These models use `AppendOnlyMixin`, which rejects ORM updates and deletes:

- `AccountStatusHistory`
- `CaseNote`
- `CaseDecision`
- `AuditEvent`

Their tables have no `updated_at` or `onupdate` columns. `CaseAlert` preserves
history differently: it is soft-unlinked by setting `unlinked_at`,
`unlinked_by_user_id`, and `unlink_reason`, and `active_alert_id` exists only
while the link is active.

## Cross-Table Rules

Some approved integrity rules involve more than one table and cannot be
expressed as MySQL `CHECK` constraints. They are enforced by the Phase 3
validation services in `app/services/validation/` and documented in
`docs/validation.md`:

- An alert's transaction, assessment, finding, and triggering rule must describe
  the same risk event.
- A case decision must reference an alert actively linked to its case and must
  not predate the earliest linked alert.
- A transfer group may be marked `RECONCILED` only after its legs reconcile.
- Transactions on closed accounts must be rejected when the transaction is
  created.

`CaseDecision.triggering_alert_id` is required at the schema level. The active
case-alert membership and earliest-alert timing checks require service-layer
queries.

## Ground-Truth Isolation

- `GroundTruth` is declared only in the separate `EvaluationBase` metadata.
- It is mapped to `yottaflex_eval.ground_truth`.
- It has no foreign keys into `yottaflex`.
- Core models contain no evaluation imports or ground-truth references.
- The risk-engine source is tested for forbidden evaluation references.
- Evaluation tools read ground truth and core results through
  `YTF_EVAL_DATABASE_URL` and `YTF_EVAL_CORE_DATABASE_URL` separately, then
  join the results in Python.
