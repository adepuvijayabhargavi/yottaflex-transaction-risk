# Model Composite Index Decisions

These indexes support expected MVP query patterns. No database was connected, and no tables were created while making these decisions.

| Table | Index | Columns | Reason |
|---|---|---|---|
| `account_status_history` | `ix_account_status_history_account_changed_at` | `account_id`, `changed_at` | Load one account's status history in chronological order. |
| `alerts` | `ix_alerts_status_created_at` | `status`, `created_at` | List alerts by status, newest first. |
| `alerts` | `ix_alerts_assigned_status_created_at` | `assigned_to_user_id`, `status`, `created_at` | Build an analyst's alert queue and sort it by age. |
| `audit_events` | `ix_audit_events_entity_occurred_at` | `entity_type`, `entity_id`, `occurred_at` | Load the audit trail for one entity in chronological order. |
| `cases` | `ix_cases_status_opened_at` | `status`, `opened_at` | List cases by status, newest first. |
| `cases` | `ix_cases_assigned_status_opened_at` | `assigned_to_user_id`, `status`, `opened_at` | Build an analyst's case queue and sort it by age. |
| `case_alerts` | `ix_case_alerts_case_id_unlinked_at` | `case_id`, `unlinked_at` | Find active case-alert links; `NULL` means still linked. |
| `case_decisions` | `ix_case_decisions_case_id_decided_at` | `case_id`, `decided_at` | Load a case's decisions in chronological order. |
| `case_notes` | `ix_case_notes_case_id_noted_at` | `case_id`, `noted_at` | Load a case's notes in chronological order. |
| `dataset_runs` | `ix_dataset_runs_status_started_at` | `status`, `started_at` | List generation runs by status, newest first. |
| `risk_assessments` | `ix_risk_assessments_transaction_assessed_at` | `transaction_id`, `assessed_at` | Load a transaction's assessments in chronological order. |
| `transactions` | `ix_transactions_debit_account_occurred_at` | `debit_account_id`, `occurred_at` | Load outgoing account activity in date order. |
| `transactions` | `ix_transactions_credit_account_occurred_at` | `credit_account_id`, `occurred_at` | Load incoming account activity in date order. |
| `validation_events` | `ix_validation_events_entity_created_at` | `entity_type`, `entity_id`, `created_at` | Load validation history for one entity. |
| `validation_events` | `ix_validation_events_resolution_created_at` | `resolution_status`, `created_at` | List open or resolved validation issues, newest first. |

## Replaced Single-Column Indexes

The leading columns above cover the single-column lookups, so these redundant indexes were removed:

- `alerts`: `ix_alerts_status`, `ix_alerts_assigned_to_user_id`
- `cases`: `ix_cases_status`, `ix_cases_assigned_to_user_id`
- `case_alerts`: `ix_case_alerts_case_id`
- `case_decisions`: `ix_case_decisions_case_id`
- `case_notes`: `ix_case_notes_case_id`
- `dataset_runs`: `ix_dataset_runs_status`
- `risk_assessments`: `ix_risk_assessments_transaction_id`
- `transactions`: `ix_transactions_debit_account_id`, `ix_transactions_credit_account_id`
- `validation_events`: `ix_validation_events_entity`, `ix_validation_events_resolution_status`
- `account_status_history`: `ix_account_status_history_account_id`
- `audit_events`: `ix_audit_events_entity`

## Unique Constraints for Rerun Safety

| Table | Constraint | Columns | Reason |
|---|---|---|---|
| `risk_assessments` | `uq_risk_assessments_transaction_model_version` | `transaction_id`, `model_version` | Prevent duplicate assessments when the same model version is rerun for the same transaction. |
| `risk_findings` | `uq_risk_findings_assessment_rule` | `assessment_id`, `rule_id` | Prevent duplicate findings for the same rule inside one assessment. |
| `alerts` | `uq_alerts_finding_id` | `finding_id` | Prevent more than one alert for the same finding. |

The unique `risk_assessments` constraint is mandatory in the Phase 1 schema. A
deliberate change to `model_version` creates a new assessment by design.

## Deliberately Not Added

Low-value or speculative combinations were not added to avoid index bloat. Examples include priority-only history indexes and extra combinations that are not yet supported by an application query.
