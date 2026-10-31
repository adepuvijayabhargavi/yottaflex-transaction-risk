# Validation Services

The Phase 3 validation layer lives in `app/services/validation/`. It performs
cross-table and business-rule checks that cannot be expressed as database
constraints. It does not create tables, run migrations, or write risk results.

## Calling a validator

Validators accept a SQLAlchemy `Session` and the entity to check. A valid entity
is returned unchanged. An invalid entity raises `ValidationError`, whose
`issue` attribute contains a machine-readable code, message, entity type,
entity ID, field, and optional details.

```python
from app.services.validation import ValidationError, validate_transaction

try:
    validate_transaction(session, transaction)
except ValidationError as error:
    session.commit()
    raise
```

By default, a rejected input also creates a `ValidationEvent` in the current
session. The caller owns the transaction and must commit it if the rejection
should be retained. Pass `record_event=False` when validating read-only data or
when the caller records the rejection separately.

## Account status transitions

Allowed transitions:

| Current status | Allowed next statuses |
|---|---|
| `ACTIVE` | `DORMANT`, `FROZEN`, `CLOSED` |
| `DORMANT` | `ACTIVE`, `FROZEN`, `CLOSED` |
| `FROZEN` | `ACTIVE`, `CLOSED` |
| `CLOSED` | None |

A status cannot transition to itself. `CLOSED` is terminal.

## Required edge cases

| Edge case | Validation code | Behavior |
|---|---|---|
| Transaction references a closed account | `TRANSACTION_CLOSED_ACCOUNT` | Reject and record a validation event. |
| Negative balance without overdraft | `NEGATIVE_BALANCE_WITHOUT_OVERDRAFT` | Reject and record a validation event. |
| Transfer legs do not reconcile | `TRANSFER_TOTALS_MISMATCH`, `TRANSFER_SOURCE_TOTAL_MISMATCH`, or `TRANSFER_DESTINATION_TOTAL_MISMATCH` | Reject the transfer group and record a validation event. |
| Alert without a triggering transaction | `ALERT_MISSING_TRANSACTION` | Reject at the service layer; the database also requires `alerts.transaction_id`. |
| Case disposition before alert creation | `CASE_DECISION_BEFORE_ALERT` | Reject and record a validation event. A decision also cannot predate its earliest active case-alert link. |

## Other enforced rules

- Primary-key references must resolve to stored records.
- Required foreign-key references must exist and belong to the correct parent.
- Transaction types must match their debit and credit accounts.
- Account, transaction, and transfer currencies must be consistent.
- Transactions cannot precede the account opening timestamp.
- Transfer source and destination amounts must equal the expected total when a
  group is `RECONCILED`; `actual_total` must also match.
- Alerts must reference the same transaction, assessment, finding, and rule.
- Case decisions require an active case-alert link and valid timestamp order.
- Append-only entities are validated but never modified by this layer.
- Dataset-run and validation-event resolution timestamps must be ordered.

## Entity coverage

Validators are provided for users, customers, merchants, devices, accounts,
account status history, transactions, transfer groups, risk rules, risk
assessments, risk findings, alerts, cases, case-alert links, case notes, case
decisions, dataset runs, validation events, and audit events.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\test_validation_edge_cases.py tests\unit\test_validation_services.py -q
```

The tests use the ephemeral SQLite schema fixture and do not touch MySQL.
