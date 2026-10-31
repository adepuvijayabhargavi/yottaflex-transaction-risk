"""Unit tests verifying rerun idempotency for the risk engine."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    Account,
    Alert,
    Customer,
    Merchant,
    RiskAssessment,
    RiskFinding,
    RiskRule,
    Transaction,
)
from app.models.enums import (
    AccountStatus,
    AccountType,
    CurrencyCode,
    RiskSeverity,
    TransactionStatus,
    TransactionType,
)
from app.services.risk_engine import (
    AlertGenerator,
    TransactionEvaluator,
    evaluate_transaction,
    run_risk_evaluation,
)
from app.services.risk_engine.rules import HighValueTransactionRule

BASE_TIME = datetime(2026, 10, 20, 12, 0, 0)


def test_evaluate_transaction_idempotency(schema_engine):
    with Session(schema_engine) as session:
        cust = Customer(
            customer_reference="CUST-IDEM-1",
            first_name="Jane",
            last_name="Doe",
            email="jane@example.com",
            country_code="US",
            onboarding_date=BASE_TIME.date(),
        )
        session.add(cust)
        session.flush()

        acc = Account(
            account_number="ACC-IDEM-01",
            customer_id=cust.id,
            account_type=AccountType.CHECKING,
            currency=CurrencyCode.USD,
            status=AccountStatus.ACTIVE,
            balance=Decimal("100000.00"),
            opened_at=BASE_TIME - timedelta(days=30),
        )
        merch = Merchant(
            merchant_reference="MERCH-IDEM-1",
            name="Luxury Goods",
            category="RETAIL",
            country_code="US",
        )
        session.add_all([acc, merch])
        session.flush()

        # Transaction of $75,000 (triggers HIGH_VALUE_TRANSACTION)
        tx = Transaction(
            transaction_reference="TXN-IDEM-1",
            debit_account_id=acc.id,
            debit_account_status_snapshot=AccountStatus.ACTIVE,
            merchant_id=merch.id,
            transaction_type=TransactionType.OUTGOING,
            status=TransactionStatus.POSTED,
            amount=Decimal("75000.00"),
            currency=CurrencyCode.USD,
            occurred_at=BASE_TIME,
        )
        rule_model = RiskRule(
            code="HIGH_VALUE_TRANSACTION",
            version=1,
            name="High value",
            category="amount",
            severity=RiskSeverity.HIGH,
            score_weight=40,
            configuration={"amount_threshold": 50000, "currency": "USD"},
            is_active=True,
        )
        session.add_all([tx, rule_model])
        session.flush()

        rule = HighValueTransactionRule(rule_model)
        evaluator = TransactionEvaluator([rule])
        alert_gen = AlertGenerator(default_threshold=40)

        # First run: should create assessment, finding, and alert
        ass1, findings1, alert1 = evaluate_transaction(
            session=session,
            transaction=tx,
            evaluator=evaluator,
            alert_generator=alert_gen,
            model_version="v1.0.0",
        )
        session.commit()

        assert ass1 is not None
        assert len(findings1) == 1
        assert alert1 is not None

        # Verify counts in DB
        assert session.scalar(select(func.count(RiskAssessment.id))) == 1
        assert session.scalar(select(func.count(RiskFinding.id))) == 1
        assert session.scalar(select(func.count(Alert.id))) == 1

        # Second run: same transaction, same model_version -> Idempotent skip!
        ass2, findings2, alert2 = evaluate_transaction(
            session=session,
            transaction=tx,
            evaluator=evaluator,
            alert_generator=alert_gen,
            model_version="v1.0.0",
        )
        session.commit()

        assert ass2 is None
        assert findings2 == []
        assert alert2 is None

        # Confirm counts did NOT increase
        assert session.scalar(select(func.count(RiskAssessment.id))) == 1
        assert session.scalar(select(func.count(RiskFinding.id))) == 1
        assert session.scalar(select(func.count(Alert.id))) == 1

        # Third run: different model_version -> creates a new assessment
        ass3, findings3, alert3 = evaluate_transaction(
            session=session,
            transaction=tx,
            evaluator=evaluator,
            alert_generator=alert_gen,
            model_version="v2.0.0",
        )
        session.commit()

        assert ass3 is not None
        assert len(findings3) == 1
        assert alert3 is not None
        assert session.scalar(select(func.count(RiskAssessment.id))) == 2


def test_batch_runner_idempotency(schema_engine):
    factory = sessionmaker(bind=schema_engine, autoflush=False, expire_on_commit=False)

    with factory() as session:
        cust = Customer(
            customer_reference="CUST-BATCH-1",
            first_name="Alice",
            last_name="Smith",
            email="alice@example.com",
            country_code="US",
            onboarding_date=BASE_TIME.date(),
        )
        session.add(cust)
        session.flush()

        acc = Account(
            account_number="ACC-BATCH-01",
            customer_id=cust.id,
            account_type=AccountType.CHECKING,
            currency=CurrencyCode.USD,
            status=AccountStatus.ACTIVE,
            balance=Decimal("200000.00"),
            opened_at=BASE_TIME - timedelta(days=30),
        )
        merch = Merchant(
            merchant_reference="MERCH-BATCH-1",
            name="Mega Corp",
            category="RETAIL",
            country_code="US",
        )
        session.add_all([acc, merch])
        session.flush()

        tx = Transaction(
            transaction_reference="TXN-BATCH-1",
            debit_account_id=acc.id,
            debit_account_status_snapshot=AccountStatus.ACTIVE,
            merchant_id=merch.id,
            transaction_type=TransactionType.OUTGOING,
            status=TransactionStatus.POSTED,
            amount=Decimal("80000.00"),
            currency=CurrencyCode.USD,
            occurred_at=BASE_TIME,
        )
        rule_model = RiskRule(
            code="HIGH_VALUE_TRANSACTION",
            version=1,
            name="High value",
            category="amount",
            severity=RiskSeverity.HIGH,
            score_weight=50,
            configuration={"amount_threshold": 50000, "currency": "USD"},
            is_active=True,
        )
        session.add_all([tx, rule_model])
        session.commit()

    # Run 1: evaluates 1 transaction
    summary1 = run_risk_evaluation(
        model_version="v1.0.0",
        session_factory=factory,
        default_threshold=40,
    )
    assert summary1.assessed_count == 1
    assert summary1.skipped_count == 0
    assert summary1.alerts_count == 1

    # Run 2: skips already-assessed transaction
    summary2 = run_risk_evaluation(
        model_version="v1.0.0",
        session_factory=factory,
        default_threshold=40,
    )
    assert summary2.assessed_count == 0
    assert summary2.skipped_count == 1
    assert summary2.alerts_count == 0
