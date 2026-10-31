"""Unit tests for the six individual risk detection rules."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import (
    Account,
    Customer,
    Device,
    Merchant,
    RiskRule,
    Transaction,
    TransferGroup,
)
from app.models.enums import (
    AccountStatus,
    AccountType,
    CurrencyCode,
    DeviceType,
    RiskSeverity,
    TransactionStatus,
    TransactionType,
    TransferStatus,
)
from app.services.risk_engine.rules import (
    CircularFundTransferRule,
    DormantAccountReactivationRule,
    HighTransactionVelocityRule,
    HighValueTransactionRule,
    NewDeviceActivityRule,
    RepeatedTransactionsRule,
)

BASE_TIME = datetime(2026, 10, 20, 12, 0, 0)


def _rule_model(
    code: str,
    weight: int,
    severity: RiskSeverity,
    config: dict,
    id_: int = 1,
) -> RiskRule:
    rule = RiskRule(
        code=code,
        version=1,
        name=f"Rule {code}",
        category="test",
        severity=severity,
        score_weight=weight,
        configuration=config,
        is_active=True,
    )
    rule.id = id_
    return rule


def _make_customer(session: Session, idx: int = 1) -> Customer:
    cust = Customer(
        customer_reference=f"CUST-{idx:04d}",
        first_name="Test",
        last_name="User",
        email=f"cust{idx}@example.com",
        country_code="US",
        onboarding_date=BASE_TIME.date(),
    )
    session.add(cust)
    session.flush()
    return cust


def _make_account(
    session: Session,
    customer: Customer,
    idx: int = 1,
    status: AccountStatus = AccountStatus.ACTIVE,
) -> Account:
    acc = Account(
        account_number=f"ACC-{idx:08d}",
        customer_id=customer.id,
        account_type=AccountType.CHECKING,
        currency=CurrencyCode.USD,
        status=status,
        balance=Decimal("5000.00"),
        opened_at=BASE_TIME - timedelta(days=120),
    )
    session.add(acc)
    session.flush()
    return acc


def _make_merchant(session: Session, idx: int = 1) -> Merchant:
    merch = Merchant(
        merchant_reference=f"MERCH-{idx:04d}",
        name=f"Merchant {idx}",
        category="RETAIL",
        country_code="US",
    )
    session.add(merch)
    session.flush()
    return merch


def _make_device(
    session: Session,
    customer: Customer,
    idx: int = 1,
    is_trusted: bool = True,
    age_hours: int = 100,
) -> Device:
    dev = Device(
        device_fingerprint=f"FINGERPRINT-{idx:06d}",
        customer_id=customer.id,
        device_type=DeviceType.MOBILE,
        first_seen_at=BASE_TIME - timedelta(hours=age_hours),
        last_seen_at=BASE_TIME,
        is_trusted=is_trusted,
    )
    session.add(dev)
    session.flush()
    return dev


def test_velocity_rule_triggers_on_four_transactions(schema_engine):
    with Session(schema_engine) as session:
        cust = _make_customer(session)
        acc = _make_account(session, cust)
        merch = _make_merchant(session)

        rule = HighTransactionVelocityRule(
            _rule_model(
                "HIGH_TRANSACTION_VELOCITY",
                20,
                RiskSeverity.HIGH,
                {"transaction_count": 4, "window_minutes": 60},
            )
        )

        txs = []
        for i in range(4):
            tx = Transaction(
                transaction_reference=f"TXN-VEL-{i}",
                debit_account_id=acc.id,
                merchant_id=merch.id,
                transaction_type=TransactionType.OUTGOING,
                status=TransactionStatus.POSTED,
                amount=Decimal("100.00"),
                currency=CurrencyCode.USD,
                occurred_at=BASE_TIME + timedelta(minutes=i * 5),
                debit_account_status_snapshot=AccountStatus.ACTIVE,
            )
            session.add(tx)
            txs.append(tx)
        session.flush()

        # All 4 transactions in this 15-minute cluster should trigger
        for tx in txs:
            match = rule.evaluate(session, tx)
            assert match is not None
            assert match.rule_code == "HIGH_TRANSACTION_VELOCITY"
            assert match.score == 20
            assert match.severity == RiskSeverity.HIGH
            assert match.evidence["transaction_count"] == 4


def test_velocity_rule_does_not_trigger_below_threshold(schema_engine):
    with Session(schema_engine) as session:
        cust = _make_customer(session)
        acc = _make_account(session, cust)
        merch = _make_merchant(session)

        rule = HighTransactionVelocityRule(
            _rule_model(
                "HIGH_TRANSACTION_VELOCITY",
                20,
                RiskSeverity.HIGH,
                {"transaction_count": 4, "window_minutes": 60},
            )
        )

        txs = []
        for i in range(3):  # only 3 transactions
            tx = Transaction(
                transaction_reference=f"TXN-VEL-LOW-{i}",
                debit_account_id=acc.id,
                merchant_id=merch.id,
                transaction_type=TransactionType.OUTGOING,
                status=TransactionStatus.POSTED,
                amount=Decimal("100.00"),
                currency=CurrencyCode.USD,
                occurred_at=BASE_TIME + timedelta(minutes=i * 5),
                debit_account_status_snapshot=AccountStatus.ACTIVE,
            )
            session.add(tx)
            txs.append(tx)
        session.flush()

        for tx in txs:
            assert rule.evaluate(session, tx) is None


def test_new_device_rule_triggers_on_untrusted_recent_device(schema_engine):
    with Session(schema_engine) as session:
        cust = _make_customer(session)
        acc = _make_account(session, cust)
        dev = _make_device(session, cust, is_trusted=False, age_hours=3)

        rule = NewDeviceActivityRule(
            _rule_model(
                "NEW_DEVICE_ACTIVITY",
                18,
                RiskSeverity.HIGH,
                {"device_age_hours": 24, "require_untrusted": True},
            )
        )

        tx = Transaction(
            transaction_reference="TXN-DEV-1",
            debit_account_id=acc.id,
            device_id=dev.id,
            transaction_type=TransactionType.OUTGOING,
            status=TransactionStatus.POSTED,
            amount=Decimal("500.00"),
            currency=CurrencyCode.USD,
            occurred_at=BASE_TIME,
            debit_account_status_snapshot=AccountStatus.ACTIVE,
        )
        session.add(tx)
        session.flush()

        match = rule.evaluate(session, tx)
        assert match is not None
        assert match.rule_code == "NEW_DEVICE_ACTIVITY"
        assert match.score == 18
        assert match.severity == RiskSeverity.HIGH
        assert match.evidence["is_trusted"] is False
        assert match.evidence["device_age_hours"] == 3.0


def test_new_device_rule_does_not_trigger_on_trusted_device(schema_engine):
    with Session(schema_engine) as session:
        cust = _make_customer(session)
        acc = _make_account(session, cust)
        dev = _make_device(session, cust, is_trusted=True, age_hours=2)

        rule = NewDeviceActivityRule(
            _rule_model(
                "NEW_DEVICE_ACTIVITY",
                18,
                RiskSeverity.HIGH,
                {"device_age_hours": 24, "require_untrusted": True},
            )
        )

        tx = Transaction(
            transaction_reference="TXN-DEV-TRUSTED",
            debit_account_id=acc.id,
            device_id=dev.id,
            transaction_type=TransactionType.OUTGOING,
            status=TransactionStatus.POSTED,
            amount=Decimal("500.00"),
            currency=CurrencyCode.USD,
            occurred_at=BASE_TIME,
            debit_account_status_snapshot=AccountStatus.ACTIVE,
        )
        session.add(tx)
        session.flush()

        assert rule.evaluate(session, tx) is None


def test_circular_transfer_triggers_on_directed_cycle(schema_engine):
    with Session(schema_engine) as session:
        cust = _make_customer(session)
        acc1 = _make_account(session, cust, idx=1)
        acc2 = _make_account(session, cust, idx=2)
        acc3 = _make_account(session, cust, idx=3)

        group = TransferGroup(
            transfer_reference="TRF-CIRC-1",
            initiated_by_customer_id=cust.id,
            status=TransferStatus.RECONCILED,
            expected_total=Decimal("300.00"),
            actual_total=Decimal("300.00"),
            currency=CurrencyCode.USD,
            reconciled_at=BASE_TIME,
        )
        session.add(group)
        session.flush()

        # Cycle: acc1 -> acc2 -> acc3 -> acc1
        pairs = [(acc1, acc2), (acc2, acc3), (acc3, acc1)]
        txs = []
        for i, (src, dst) in enumerate(pairs):
            tx = Transaction(
                transaction_reference=f"TXN-CIRC-{i}",
                transfer_group_id=group.id,
                debit_account_id=src.id,
                credit_account_id=dst.id,
                transaction_type=TransactionType.INTERNAL,
                status=TransactionStatus.POSTED,
                amount=Decimal("100.00"),
                currency=CurrencyCode.USD,
                occurred_at=BASE_TIME + timedelta(hours=i * 2),
                debit_account_status_snapshot=AccountStatus.ACTIVE,
                credit_account_status_snapshot=AccountStatus.ACTIVE,
            )
            session.add(tx)
            txs.append(tx)
        session.flush()

        rule = CircularFundTransferRule(
            _rule_model(
                "CIRCULAR_FUND_TRANSFER",
                30,
                RiskSeverity.CRITICAL,
                {"window_hours": 24, "max_cycle_length": 4},
            )
        )

        for tx in txs:
            match = rule.evaluate(session, tx)
            assert match is not None
            assert match.rule_code == "CIRCULAR_FUND_TRANSFER"
            assert match.score == 30
            assert match.severity == RiskSeverity.CRITICAL
            assert match.evidence["cycle_length"] == 3


def test_dormant_reactivation_triggers_on_dormant_snapshot(schema_engine):
    with Session(schema_engine) as session:
        cust = _make_customer(session)
        acc = _make_account(session, cust, status=AccountStatus.DORMANT)
        merch = _make_merchant(session)

        rule = DormantAccountReactivationRule(
            _rule_model(
                "DORMANT_ACCOUNT_REACTIVATION",
                22,
                RiskSeverity.HIGH,
                {"dormant_days": 90},
            )
        )

        tx = Transaction(
            transaction_reference="TXN-DORM-1",
            debit_account_id=acc.id,
            merchant_id=merch.id,
            transaction_type=TransactionType.OUTGOING,
            status=TransactionStatus.POSTED,
            amount=Decimal("50.00"),
            currency=CurrencyCode.USD,
            occurred_at=BASE_TIME,
            debit_account_status_snapshot=AccountStatus.DORMANT,
        )
        session.add(tx)
        session.flush()

        match = rule.evaluate(session, tx)
        assert match is not None
        assert match.rule_code == "DORMANT_ACCOUNT_REACTIVATION"
        assert match.score == 22
        assert match.severity == RiskSeverity.HIGH
        assert match.evidence["is_dormant_snapshot"] is True


def test_high_value_rule_triggers_at_or_above_fifty_thousand(schema_engine):
    with Session(schema_engine) as session:
        cust = _make_customer(session)
        acc = _make_account(session, cust)
        merch = _make_merchant(session)

        rule = HighValueTransactionRule(
            _rule_model(
                "HIGH_VALUE_TRANSACTION",
                20,
                RiskSeverity.HIGH,
                {"amount_threshold": 50000, "currency": "USD"},
            )
        )

        tx_match = Transaction(
            transaction_reference="TXN-HV-1",
            debit_account_id=acc.id,
            merchant_id=merch.id,
            transaction_type=TransactionType.OUTGOING,
            status=TransactionStatus.POSTED,
            amount=Decimal("50000.00"),
            currency=CurrencyCode.USD,
            occurred_at=BASE_TIME,
            debit_account_status_snapshot=AccountStatus.ACTIVE,
        )
        tx_nomatch = Transaction(
            transaction_reference="TXN-HV-2",
            debit_account_id=acc.id,
            merchant_id=merch.id,
            transaction_type=TransactionType.OUTGOING,
            status=TransactionStatus.POSTED,
            amount=Decimal("49999.99"),
            currency=CurrencyCode.USD,
            occurred_at=BASE_TIME,
            debit_account_status_snapshot=AccountStatus.ACTIVE,
        )
        session.add_all([tx_match, tx_nomatch])
        session.flush()

        match = rule.evaluate(session, tx_match)
        assert match is not None
        assert match.score == 20
        assert match.severity == RiskSeverity.HIGH

        assert rule.evaluate(session, tx_nomatch) is None


def test_repeated_transactions_triggers_on_three_repeats(schema_engine):
    with Session(schema_engine) as session:
        cust = _make_customer(session)
        acc = _make_account(session, cust)
        merch = _make_merchant(session)

        rule = RepeatedTransactionsRule(
            _rule_model(
                "REPEATED_TRANSACTIONS",
                15,
                RiskSeverity.MEDIUM,
                {"repeat_count": 3, "window_minutes": 30},
            )
        )

        amount = Decimal("1234.56")
        txs = []
        for i in range(3):
            tx = Transaction(
                transaction_reference=f"TXN-REP-{i}",
                debit_account_id=acc.id,
                merchant_id=merch.id,
                transaction_type=TransactionType.OUTGOING,
                status=TransactionStatus.POSTED,
                amount=amount,
                currency=CurrencyCode.USD,
                occurred_at=BASE_TIME + timedelta(minutes=i * 2),
                debit_account_status_snapshot=AccountStatus.ACTIVE,
            )
            session.add(tx)
            txs.append(tx)
        session.flush()

        for tx in txs:
            match = rule.evaluate(session, tx)
            assert match is not None
            assert match.rule_code == "REPEATED_TRANSACTIONS"
            assert match.score == 15
            assert match.severity == RiskSeverity.MEDIUM
            assert match.evidence["repeat_count"] == 3
