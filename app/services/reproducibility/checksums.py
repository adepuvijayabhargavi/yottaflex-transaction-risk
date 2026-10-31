"""Canonical SHA-256 checksums for generated datasets."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.evaluation import GroundTruth
from app.models import (
    Account,
    AccountStatusHistory,
    Customer,
    Device,
    Merchant,
    RiskRule,
    Transaction,
    TransferGroup,
)


def canonical_value(value: Any) -> Any:
    """Convert a database value into a stable, JSON-compatible value."""

    if value is None:
        return None
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return format(value.quantize(Decimal("0.01")), "f")
    if isinstance(value, datetime):
        return value.replace(tzinfo=None).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        return {
            str(key): canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [canonical_value(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    """Serialize a value using a stable JSON representation."""

    return json.dumps(
        canonical_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def checksum_table(
    table_name: str,
    rows: Iterable[dict[str, Any]],
    *,
    key_fields: Sequence[str],
) -> str:
    """Return a canonical SHA-256 digest for a table's business rows."""

    ordered_rows: list[tuple[str, str]] = []
    for row in rows:
        key = canonical_json([row.get(field) for field in key_fields])
        ordered_rows.append((key, canonical_json(row)))
    ordered_rows.sort(key=lambda item: item[0])

    digest = hashlib.sha256()
    digest.update(f"{table_name}\n".encode())
    for key, row in ordered_rows:
        digest.update(key.encode())
        digest.update(b"\n")
        digest.update(row.encode())
        digest.update(b"\n")
    return digest.hexdigest()


def _overall_checksum(table_checksums: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for table_name, checksum in sorted(table_checksums.items()):
        digest.update(f"{table_name}:{checksum}\n".encode())
    return digest.hexdigest()


def compute_run_checksums(
    core_session: Session,
    eval_session: Session,
    *,
    run_reference: str,
) -> dict[str, Any]:
    """Compute stable per-table and overall checksums for one dataset run."""

    customers = core_session.scalars(select(Customer)).all()
    accounts = core_session.scalars(select(Account)).all()
    histories = core_session.scalars(select(AccountStatusHistory)).all()
    merchants = core_session.scalars(select(Merchant)).all()
    devices = core_session.scalars(select(Device)).all()
    transfer_groups = core_session.scalars(select(TransferGroup)).all()
    transactions = core_session.scalars(select(Transaction)).all()
    risk_rules = core_session.scalars(select(RiskRule)).all()
    ground_truth = eval_session.scalars(
        select(GroundTruth).where(
            GroundTruth.dataset_run_reference == run_reference,
        )
    ).all()

    customer_by_id = {row.id: row.customer_reference for row in customers}
    account_by_id = {row.id: row.account_number for row in accounts}
    merchant_by_id = {row.id: row.merchant_reference for row in merchants}
    device_by_id = {row.id: row.device_fingerprint for row in devices}
    transfer_by_id = {row.id: row.transfer_reference for row in transfer_groups}

    table_rows: dict[str, tuple[list[dict[str, Any]], tuple[str, ...]]] = {
        "customers": (
            [
                {
                    "customer_reference": row.customer_reference,
                    "first_name": row.first_name,
                    "last_name": row.last_name,
                    "email": row.email,
                    "phone": row.phone,
                    "country_code": row.country_code,
                    "risk_segment": row.risk_segment,
                    "onboarding_date": row.onboarding_date,
                    "is_active": row.is_active,
                }
                for row in customers
            ],
            ("customer_reference",),
        ),
        "accounts": (
            [
                {
                    "account_number": row.account_number,
                    "customer_reference": customer_by_id[row.customer_id],
                    "account_type": row.account_type,
                    "currency": row.currency,
                    "status": row.status,
                    "balance": row.balance,
                    "overdraft_limit": row.overdraft_limit,
                    "opened_at": row.opened_at,
                    "closed_at": row.closed_at,
                }
                for row in accounts
            ],
            ("account_number",),
        ),
        "account_status_history": (
            [
                {
                    "account_number": account_by_id[row.account_id],
                    "previous_status": row.previous_status,
                    "new_status": row.new_status,
                    "reason": row.reason,
                    "changed_at": row.changed_at,
                }
                for row in histories
            ],
            ("account_number", "changed_at", "new_status"),
        ),
        "merchants": (
            [
                {
                    "merchant_reference": row.merchant_reference,
                    "name": row.name,
                    "category": row.category,
                    "country_code": row.country_code,
                    "risk_level": row.risk_level,
                    "is_active": row.is_active,
                }
                for row in merchants
            ],
            ("merchant_reference",),
        ),
        "devices": (
            [
                {
                    "device_fingerprint": row.device_fingerprint,
                    "customer_reference": customer_by_id[row.customer_id],
                    "device_type": row.device_type,
                    "first_seen_at": row.first_seen_at,
                    "last_seen_at": row.last_seen_at,
                    "is_trusted": row.is_trusted,
                }
                for row in devices
            ],
            ("device_fingerprint",),
        ),
        "transfer_groups": (
            [
                {
                    "transfer_reference": row.transfer_reference,
                    "initiated_by_customer_reference": (
                        customer_by_id.get(row.initiated_by_customer_id)
                        if row.initiated_by_customer_id is not None
                        else None
                    ),
                    "status": row.status,
                    "expected_total": row.expected_total,
                    "actual_total": row.actual_total,
                    "currency": row.currency,
                    "reconciled_at": row.reconciled_at,
                }
                for row in transfer_groups
            ],
            ("transfer_reference",),
        ),
        "transactions": (
            [
                {
                    "transaction_reference": row.transaction_reference,
                    "transfer_reference": transfer_by_id.get(row.transfer_group_id),
                    "debit_account_number": account_by_id.get(row.debit_account_id),
                    "credit_account_number": account_by_id.get(row.credit_account_id),
                    "merchant_reference": merchant_by_id.get(row.merchant_id),
                    "device_fingerprint": device_by_id.get(row.device_id),
                    "transaction_type": row.transaction_type,
                    "status": row.status,
                    "amount": row.amount,
                    "currency": row.currency,
                    "occurred_at": row.occurred_at,
                    "description": row.description,
                    "debit_account_status_snapshot": row.debit_account_status_snapshot,
                    "credit_account_status_snapshot": row.credit_account_status_snapshot,
                }
                for row in transactions
            ],
            ("transaction_reference",),
        ),
        "risk_rules": (
            [
                {
                    "code": row.code,
                    "version": row.version,
                    "name": row.name,
                    "description": row.description,
                    "category": row.category,
                    "severity": row.severity,
                    "score_weight": row.score_weight,
                    "configuration": row.configuration,
                    "is_active": row.is_active,
                    "effective_from": row.effective_from,
                    "effective_to": row.effective_to,
                }
                for row in risk_rules
            ],
            ("code", "version"),
        ),
        "ground_truth": (
            [
                {
                    "ground_truth_reference": row.ground_truth_reference,
                    "dataset_run_reference": row.dataset_run_reference,
                    "transaction_reference": row.transaction_reference,
                    "is_fraud": row.is_fraud,
                    "primary_pattern": row.primary_pattern,
                    "pattern_codes": row.pattern_codes,
                    "label_source": row.label_source,
                    "generation_metadata": row.generation_metadata,
                }
                for row in ground_truth
            ],
            ("ground_truth_reference",),
        ),
    }

    table_checksums = {
        table_name: checksum_table(table_name, rows, key_fields=key_fields)
        for table_name, (rows, key_fields) in table_rows.items()
    }
    return {
        "tables": table_checksums,
        "overall": _overall_checksum(table_checksums),
    }
