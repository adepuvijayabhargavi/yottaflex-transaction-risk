"""End-to-end verification for one generated dataset run."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.evaluation import GroundTruth
from app.models import (
    Account,
    AccountStatusHistory,
    Alert,
    Customer,
    DatasetRun,
    Device,
    Merchant,
    RiskRule,
    Transaction,
    TransferGroup,
)
from app.models.base import SCHEMA as CORE_SCHEMA
from app.models.enums import DatasetRunStatus, TransactionStatus, TransferStatus
from app.services.reproducibility.checksums import compute_run_checksums

from .generator import (
    GENERATOR_VERSION,
    OPENING_BALANCE,
    PATTERN_COUNTS,
)
from .profiles import DatasetProfile


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """The complete result of a dataset verification run."""

    run_reference: str
    ok: bool
    counts: dict[str, int]
    expected_counts: dict[str, int]
    pattern_counts: dict[str, int]
    checksums: dict[str, Any]
    errors: tuple[str, ...]


def _expected_counts(profile: DatasetProfile) -> dict[str, int]:
    return {
        "customers": profile.target("customers"),
        "accounts": profile.target("accounts"),
        "merchants": profile.target("merchants"),
        "devices": profile.target("devices"),
        "transfer_groups": profile.target("transfer_groups"),
        "transactions": profile.target("transactions"),
        "risk_rules": profile.target("risk_rules"),
        "ground_truth": profile.target("transactions"),
        "ground_truth_positive": sum(PATTERN_COUNTS.values()),
        "alerts": 0,
    }


def _actual_counts(
    core_session: Session,
    eval_session: Session,
    result_session: Session,
    *,
    run_reference: str,
    prefix: str,
) -> dict[str, int]:
    account_ids = select(Account.id).where(
        Account.account_number.startswith(prefix),
    )
    transaction_ids = select(Transaction.id).where(
        Transaction.transaction_reference.startswith(prefix),
    )
    return {
        "customers": int(
            core_session.scalar(
                select(func.count())
                .select_from(Customer)
                .where(Customer.customer_reference.startswith(prefix))
            )
            or 0
        ),
        "accounts": int(
            core_session.scalar(
                select(func.count())
                .select_from(Account)
                .where(Account.account_number.startswith(prefix))
            )
            or 0
        ),
        "account_status_history": int(
            core_session.scalar(
                select(func.count())
                .select_from(AccountStatusHistory)
                .where(AccountStatusHistory.account_id.in_(account_ids))
            )
            or 0
        ),
        "merchants": int(
            core_session.scalar(
                select(func.count())
                .select_from(Merchant)
                .where(Merchant.merchant_reference.startswith(prefix))
            )
            or 0
        ),
        "devices": int(
            core_session.scalar(
                select(func.count())
                .select_from(Device)
                .where(Device.device_fingerprint.startswith(prefix))
            )
            or 0
        ),
        "transfer_groups": int(
            core_session.scalar(
                select(func.count())
                .select_from(TransferGroup)
                .where(TransferGroup.transfer_reference.startswith(prefix))
            )
            or 0
        ),
        "transactions": int(
            core_session.scalar(
                select(func.count())
                .select_from(Transaction)
                .where(Transaction.transaction_reference.startswith(prefix))
            )
            or 0
        ),
        "risk_rules": int(
            core_session.scalar(select(func.count()).select_from(RiskRule)) or 0
        ),
        "dataset_runs": int(
            core_session.scalar(
                select(func.count())
                .select_from(DatasetRun)
                .where(DatasetRun.run_reference == run_reference)
            )
            or 0
        ),
        "ground_truth": int(
            eval_session.scalar(
                select(func.count())
                .select_from(GroundTruth)
                .where(GroundTruth.dataset_run_reference == run_reference)
            )
            or 0
        ),
        "ground_truth_positive": int(
            eval_session.scalar(
                select(func.count())
                .select_from(GroundTruth)
                .where(
                    GroundTruth.dataset_run_reference == run_reference,
                    GroundTruth.is_fraud.is_(True),
                )
            )
            or 0
        ),
        "alerts": int(
            result_session.scalar(
                select(func.count())
                .select_from(Alert)
                .where(Alert.transaction_id.in_(transaction_ids))
            )
            or 0
        ),
    }


def _check_metadata(errors: list[str]) -> None:
    if GroundTruth.__table__.schema != "yottaflex_eval":
        errors.append("Ground truth is not isolated in the yottaflex_eval schema.")
    if any(
        table is GroundTruth.__table__ for table in Transaction.metadata.tables.values()
    ):
        errors.append("Ground truth is registered in the core SQLAlchemy metadata.")
    if any(
        table.schema != CORE_SCHEMA for table in Transaction.metadata.tables.values()
    ):
        errors.append("A core table is registered outside the yottaflex schema.")
    if any(
        foreign_key.column.table.schema != CORE_SCHEMA
        for table in Transaction.metadata.tables.values()
        for foreign_key in table.foreign_keys
    ):
        errors.append("A core foreign key crosses outside the yottaflex schema.")
    if GroundTruth.__table__.foreign_keys:
        errors.append("Ground truth must not have database foreign keys.")


def _check_ground_truth(
    transactions: list[Transaction],
    ground_truth: list[GroundTruth],
    *,
    run_reference: str,
    prefix: str,
    errors: list[str],
) -> dict[str, int]:
    transaction_references = {
        transaction.transaction_reference for transaction in transactions
    }
    label_references = {label.transaction_reference for label in ground_truth}
    if label_references != transaction_references:
        missing = sorted(transaction_references - label_references)
        extra = sorted(label_references - transaction_references)
        errors.append(
            "Ground truth does not cover the run's transactions. "
            f"Missing={missing[:5]}; extra={extra[:5]}."
        )

    pattern_counts = Counter(
        label.primary_pattern for label in ground_truth if label.is_fraud
    )
    actual_patterns = {
        pattern: pattern_counts.get(pattern, 0) for pattern in PATTERN_COUNTS
    }
    if actual_patterns != PATTERN_COUNTS:
        errors.append(
            "Fraud-label distribution differs from the documented patterns. "
            f"Expected={PATTERN_COUNTS}; actual={actual_patterns}."
        )

    for label in ground_truth:
        if label.dataset_run_reference != run_reference:
            errors.append("Ground truth contains a label from another run.")
            break
        if not label.ground_truth_reference.startswith(prefix):
            errors.append("Ground truth reference does not use the run prefix.")
            break
        if label.label_source != "SYNTHETIC_GENERATOR":
            errors.append("Ground truth contains an unexpected label source.")
            break
        if label.is_fraud and not label.primary_pattern:
            errors.append("A fraud label is missing its primary pattern.")
            break
        if not label.is_fraud and (
            label.primary_pattern is not None or label.pattern_codes
        ):
            errors.append("A negative label contains fraud-pattern data.")
            break
    return actual_patterns


def _check_balances(
    accounts: list[Account],
    transactions: list[Transaction],
    errors: list[str],
) -> None:
    balances = {account.id: OPENING_BALANCE for account in accounts}
    for transaction in transactions:
        if transaction.status != TransactionStatus.POSTED:
            continue
        if transaction.debit_account_id is not None:
            balances[transaction.debit_account_id] -= transaction.amount
        if transaction.credit_account_id is not None:
            balances[transaction.credit_account_id] += transaction.amount

    for account in accounts:
        expected = balances[account.id].quantize(Decimal("0.01"))
        if account.balance != expected:
            errors.append(
                f"Balance mismatch for {account.account_number}: "
                f"stored={account.balance}, expected={expected}."
            )
            break


def _check_transfers(
    transfer_groups: list[TransferGroup],
    transactions: list[Transaction],
    errors: list[str],
) -> None:
    legs_by_group: dict[int, list[Transaction]] = defaultdict(list)
    for transaction in transactions:
        if transaction.transfer_group_id is not None:
            legs_by_group[transaction.transfer_group_id].append(transaction)

    for group in transfer_groups:
        legs = legs_by_group.get(group.id, [])
        if len(legs) != 3:
            errors.append(
                f"Transfer group {group.transfer_reference} has {len(legs)} legs."
            )
            continue
        expected_total = sum(
            (leg.amount for leg in legs),
            Decimal("0.00"),
        )
        actual_total = sum(
            (leg.amount for leg in legs if leg.status == TransactionStatus.POSTED),
            Decimal("0.00"),
        )
        if group.expected_total != expected_total:
            errors.append(f"Expected total mismatch for {group.transfer_reference}.")
        if group.actual_total != actual_total:
            errors.append(f"Actual total mismatch for {group.transfer_reference}.")
        if group.status == TransferStatus.RECONCILED:
            if group.reconciled_at is None:
                errors.append(
                    f"Reconciled group {group.transfer_reference} has no timestamp."
                )
            if group.actual_total != group.expected_total:
                errors.append(
                    f"Reconciled group {group.transfer_reference} is not balanced."
                )
        elif group.reconciled_at is not None:
            errors.append(
                f"Unreconciled group {group.transfer_reference} has a timestamp."
            )


def verify_dataset_run(
    core_session: Session,
    eval_session: Session,
    profile: DatasetProfile,
    *,
    run_reference: str,
    result_session: Session | None = None,
) -> VerificationResult:
    """Verify counts, labels, balances, transfers, isolation, and checksums."""

    prefix = f"{run_reference}-"
    errors: list[str] = []
    alert_session = result_session or core_session
    run = core_session.scalar(
        select(DatasetRun).where(DatasetRun.run_reference == run_reference)
    )
    if run is None:
        errors.append(f"Dataset run {run_reference!r} does not exist.")
    elif run.status != DatasetRunStatus.COMPLETED:
        errors.append(f"Dataset run {run_reference!r} is not complete.")

    counts = _actual_counts(
        core_session,
        eval_session,
        alert_session,
        run_reference=run_reference,
        prefix=prefix,
    )
    expected_counts = _expected_counts(profile)
    for key, expected in expected_counts.items():
        if counts[key] != expected:
            errors.append(
                f"Count mismatch for {key}: actual={counts[key]}, expected={expected}."
            )

    if run is not None:
        if run.profile_name != profile.name:
            errors.append("Dataset run profile name does not match the profile.")
        if run.seed != profile.seed:
            errors.append("Dataset run seed does not match the profile.")
        if run.reference_datetime_utc != profile.reference_datetime:
            errors.append("Dataset run reference time does not match the profile.")
        for key, value in run.record_counts.items():
            if key in counts and counts[key] != value:
                errors.append(
                    f"Stored record count for {key} does not match the database."
                )

    accounts = core_session.scalars(
        select(Account).where(Account.account_number.startswith(prefix))
    ).all()
    transactions = core_session.scalars(
        select(Transaction).where(Transaction.transaction_reference.startswith(prefix))
    ).all()
    transfer_groups = core_session.scalars(
        select(TransferGroup).where(TransferGroup.transfer_reference.startswith(prefix))
    ).all()
    ground_truth = eval_session.scalars(
        select(GroundTruth).where(GroundTruth.dataset_run_reference == run_reference)
    ).all()

    pattern_counts = _check_ground_truth(
        list(transactions),
        list(ground_truth),
        run_reference=run_reference,
        prefix=prefix,
        errors=errors,
    )
    _check_balances(list(accounts), list(transactions), errors)
    _check_transfers(list(transfer_groups), list(transactions), errors)
    _check_metadata(errors)

    checksums = compute_run_checksums(
        core_session,
        eval_session,
        run_reference=run_reference,
    )
    if run is not None:
        stored_tables = run.checksums.get("tables", {})
        if stored_tables != checksums["tables"]:
            errors.append("Stored per-table checksums do not match the database.")
        if run.checksums.get("overall") != checksums["overall"]:
            errors.append("Stored overall checksum does not match the database.")
        if run.checksums.get("generator_version") != GENERATOR_VERSION:
            errors.append("Stored generator version does not match this generator.")

    return VerificationResult(
        run_reference=run_reference,
        ok=not errors,
        counts=counts,
        expected_counts=expected_counts,
        pattern_counts=pattern_counts,
        checksums=checksums,
        errors=tuple(errors),
    )
