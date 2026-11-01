"""Deterministic pilot generation, reset, and verification tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
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
from app.models.enums import TransactionStatus, TransferStatus
from app.services.data_generator import (
    generate_dataset,
    load_profile,
    reset_dataset_run,
    verify_dataset_run,
)
from app.services.data_generator.generator import OPENING_BALANCE, PATTERN_COUNTS
from app.services.reproducibility import compute_run_checksums

RUN_REFERENCE = "PILOT-20261022"


@pytest.fixture()
def pilot_profile():
    return load_profile("pilot")


def _generate(schema_engine, profile, *, run_reference=None):
    with Session(schema_engine, expire_on_commit=False) as session:
        result = generate_dataset(
            profile,
            session,
            session,
            run_reference=run_reference,
        )
        session.commit()
        return result


def _count(session, model, *where) -> int:
    return int(
        session.scalar(select(func.count()).select_from(model).where(*where)) or 0
    )


def _assert_empty(session: Session) -> None:
    for model in (
        GroundTruth,
        Transaction,
        TransferGroup,
        AccountStatusHistory,
        Account,
        Device,
        Merchant,
        Customer,
        DatasetRun,
    ):
        assert _count(session, model) == 0, model
    assert _count(session, RiskRule) == 12
    assert _count(session, Alert) == 0


def test_pilot_generation_matches_profile_and_labels(schema_engine, pilot_profile):
    result = _generate(schema_engine, pilot_profile)

    with Session(schema_engine) as session:
        assert result.counts["customers"] == 100
        assert result.counts["accounts"] == 150
        assert result.counts["merchants"] == 50
        assert result.counts["devices"] == 300
        assert result.counts["transfer_groups"] == 100
        assert result.counts["transactions"] == 2000
        assert result.counts["risk_rules"] == 12
        assert result.counts["ground_truth"] == 2000
        assert result.counts["ground_truth_positive"] == 20
        assert result.counts["alerts"] == 0
        assert result.counts["fraud_labels_by_pattern"] == PATTERN_COUNTS

        assert _count(session, Transaction) == 2000
        assert _count(session, GroundTruth) == 2000
        assert _count(session, GroundTruth, GroundTruth.is_fraud.is_(True)) == 20
        assert _count(session, Alert) == 0
        assert (
            _count(
                session,
                Account,
                Account.balance < Decimal("0.00"),
            )
            == 0
        )


def test_pilot_verification_passes(schema_engine, pilot_profile):
    _generate(schema_engine, pilot_profile)

    with Session(schema_engine) as session:
        result = verify_dataset_run(
            session,
            session,
            pilot_profile,
            run_reference=RUN_REFERENCE,
        )

    assert result.ok, result.errors
    assert result.counts["account_status_history"] == 22
    assert result.counts["dataset_runs"] == 1
    assert result.pattern_counts == PATTERN_COUNTS
    for key, expected in result.expected_counts.items():
        assert result.counts[key] == expected


def test_pilot_generation_is_reproducible_after_reset(schema_engine, pilot_profile):
    first = _generate(schema_engine, pilot_profile)

    with Session(schema_engine) as session:
        reset_dataset_run(
            session,
            run_reference=RUN_REFERENCE,
            dry_run=False,
        )
        session.commit()
        _assert_empty(session)

    second = _generate(schema_engine, pilot_profile)

    assert first.checksums["tables"] == second.checksums["tables"]
    assert first.checksums["overall"] == second.checksums["overall"]


def test_run_checksums_exclude_other_generated_runs(schema_engine, pilot_profile):
    first = _generate(schema_engine, pilot_profile)
    with Session(schema_engine) as session:
        before = compute_run_checksums(
            session,
            session,
            run_reference=RUN_REFERENCE,
        )

    with Session(schema_engine) as session:
        session.add(
            Customer(
                customer_reference="ALT-1-CUST-0001",
                first_name="Other",
                last_name="Run",
                email="other.run@example.test",
                country_code="US",
                onboarding_date=date(2026, 10, 30),
            )
        )
        session.commit()

    with Session(schema_engine) as session:
        after = compute_run_checksums(
            session,
            session,
            run_reference=RUN_REFERENCE,
        )

    assert (
        before
        == after
        == {
            "tables": first.checksums["tables"],
            "overall": first.checksums["overall"],
        }
    )


def test_reset_dry_run_preserves_generated_data(schema_engine, pilot_profile):
    _generate(schema_engine, pilot_profile)

    with Session(schema_engine) as session:
        result = reset_dataset_run(
            session,
            run_reference=RUN_REFERENCE,
            dry_run=True,
        )
        assert result.dry_run is True
        assert result.counts["transactions"] == 2000
        assert result.counts["ground_truth"] == 2000
        assert _count(session, Transaction) == 2000
        assert _count(session, GroundTruth) == 2000
        assert _count(session, DatasetRun) == 1
        assert _count(session, RiskRule) == 12


def test_confirmed_reset_removes_only_the_run(schema_engine, pilot_profile):
    _generate(schema_engine, pilot_profile)

    with Session(schema_engine) as session:
        result = reset_dataset_run(
            session,
            run_reference=RUN_REFERENCE,
            dry_run=False,
        )
        session.commit()
        assert result.dry_run is False
        assert result.counts["transactions"] == 2000
        assert result.counts["dataset_runs"] == 1
        _assert_empty(session)


def test_verification_detects_tampered_checksum(schema_engine, pilot_profile):
    _generate(schema_engine, pilot_profile)

    with Session(schema_engine) as session:
        run = session.scalar(
            select(DatasetRun).where(DatasetRun.run_reference == RUN_REFERENCE)
        )
        assert run is not None
        run.checksums = {**run.checksums, "overall": "0" * 64}
        session.commit()

    with Session(schema_engine) as session:
        result = verify_dataset_run(
            session,
            session,
            pilot_profile,
            run_reference=RUN_REFERENCE,
        )

    assert result.ok is False
    assert any("overall checksum" in error for error in result.errors)


def test_pilot_transfer_groups_reconcile(schema_engine, pilot_profile):
    _generate(schema_engine, pilot_profile)

    with Session(schema_engine) as session:
        groups = session.scalars(select(TransferGroup)).all()
        transactions = session.scalars(select(Transaction)).all()

    assert len(groups) == 100
    by_group: dict[int, list[Transaction]] = {}
    for transaction in transactions:
        if transaction.transfer_group_id is not None:
            by_group.setdefault(transaction.transfer_group_id, []).append(transaction)

    for group in groups:
        legs = by_group[group.id]
        assert len(legs) == 3
        expected = sum((leg.amount for leg in legs), Decimal("0.00"))
        actual = sum(
            (leg.amount for leg in legs if leg.status == TransactionStatus.POSTED),
            Decimal("0.00"),
        )
        assert group.expected_total == expected
        assert group.actual_total == actual
        if group.status == TransferStatus.RECONCILED:
            assert group.reconciled_at is not None
            assert group.actual_total == group.expected_total
        else:
            assert group.reconciled_at is None


def test_pilot_balances_start_from_opening_balance(schema_engine, pilot_profile):
    _generate(schema_engine, pilot_profile)

    with Session(schema_engine) as session:
        accounts = session.scalars(select(Account)).all()
        transactions = session.scalars(select(Transaction)).all()

    balances = {account.id: OPENING_BALANCE for account in accounts}
    for transaction in transactions:
        if transaction.status != TransactionStatus.POSTED:
            continue
        if transaction.debit_account_id is not None:
            balances[transaction.debit_account_id] -= transaction.amount
        if transaction.credit_account_id is not None:
            balances[transaction.credit_account_id] += transaction.amount

    for account in accounts:
        assert account.balance == balances[account.id].quantize(Decimal("0.01"))
