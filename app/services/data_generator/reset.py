"""Deterministic, FK-safe removal of one generated dataset run."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.evaluation import GroundTruth
from app.models import (
    Account,
    AccountStatusHistory,
    Customer,
    DatasetRun,
    Device,
    Merchant,
    Transaction,
    TransferGroup,
)


@dataclass(frozen=True, slots=True)
class ResetResult:
    """Summary of a dataset reset or reset dry run."""

    run_reference: str
    dry_run: bool
    counts: dict[str, int]


def _prefix(run_reference: str) -> str:
    value = run_reference.strip()
    if not value:
        raise ValueError("run_reference must not be blank.")
    return f"{value}-"


def _count(session: Session, statement) -> int:
    return int(session.scalar(statement) or 0)


def _run_counts(session: Session, run_reference: str, prefix: str) -> dict[str, int]:
    account_ids = select(Account.id).where(
        Account.account_number.startswith(prefix),
    )
    return {
        "ground_truth": _count(
            session,
            select(func.count())
            .select_from(GroundTruth)
            .where(GroundTruth.dataset_run_reference == run_reference),
        ),
        "transactions": _count(
            session,
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.transaction_reference.startswith(prefix)),
        ),
        "transfer_groups": _count(
            session,
            select(func.count())
            .select_from(TransferGroup)
            .where(TransferGroup.transfer_reference.startswith(prefix)),
        ),
        "account_status_history": _count(
            session,
            select(func.count())
            .select_from(AccountStatusHistory)
            .where(AccountStatusHistory.account_id.in_(account_ids)),
        ),
        "accounts": _count(
            session,
            select(func.count())
            .select_from(Account)
            .where(Account.account_number.startswith(prefix)),
        ),
        "devices": _count(
            session,
            select(func.count())
            .select_from(Device)
            .where(Device.device_fingerprint.startswith(prefix)),
        ),
        "merchants": _count(
            session,
            select(func.count())
            .select_from(Merchant)
            .where(Merchant.merchant_reference.startswith(prefix)),
        ),
        "customers": _count(
            session,
            select(func.count())
            .select_from(Customer)
            .where(Customer.customer_reference.startswith(prefix)),
        ),
        "dataset_runs": _count(
            session,
            select(func.count())
            .select_from(DatasetRun)
            .where(DatasetRun.run_reference == run_reference),
        ),
    }


def reset_dataset_run(
    session: Session,
    *,
    run_reference: str,
    dry_run: bool,
) -> ResetResult:
    """Delete one run's generated data without touching versioned risk rules."""

    prefix = _prefix(run_reference)
    counts = _run_counts(session, run_reference, prefix)
    if dry_run or not any(counts.values()):
        return ResetResult(run_reference=run_reference, dry_run=dry_run, counts=counts)

    account_ids = select(Account.id).where(
        Account.account_number.startswith(prefix),
    )
    statements = (
        delete(GroundTruth).where(
            GroundTruth.dataset_run_reference == run_reference,
        ),
        delete(Transaction).where(
            Transaction.transaction_reference.startswith(prefix),
        ),
        delete(TransferGroup).where(
            TransferGroup.transfer_reference.startswith(prefix),
        ),
        delete(AccountStatusHistory).where(
            AccountStatusHistory.account_id.in_(account_ids),
        ),
        delete(Account).where(Account.account_number.startswith(prefix)),
        delete(Device).where(Device.device_fingerprint.startswith(prefix)),
        delete(Merchant).where(Merchant.merchant_reference.startswith(prefix)),
        delete(Customer).where(Customer.customer_reference.startswith(prefix)),
        delete(DatasetRun).where(DatasetRun.run_reference == run_reference),
    )
    for statement in statements:
        session.execute(statement)
    session.flush()

    return ResetResult(run_reference=run_reference, dry_run=False, counts=counts)
