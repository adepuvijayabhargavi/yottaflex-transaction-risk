"""Database-level constraint checks using an ephemeral SQLite schema."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.evaluation import GroundTruth
from app.models import (
    Account,
    AccountStatusHistory,
    Alert,
    AuditEvent,
    Case,
    CaseAlert,
    CaseDecision,
    Customer,
    RiskAssessment,
    RiskFinding,
    RiskRule,
    Transaction,
    User,
)
from app.models.base import AppendOnlyError, utc_now
from app.models.enums import (
    AccountStatus,
    AccountType,
    AlertPriority,
    AlertStatus,
    AssessmentStatus,
    CaseDecisionType,
    CasePriority,
    CaseStatus,
    CurrencyCode,
    RiskLevel,
    RiskSeverity,
    TransactionStatus,
    TransactionType,
    UserRole,
)


def _user(session: Session, suffix: str = "1") -> User:
    user = User(
        username=f"analyst-{suffix}",
        email=f"analyst-{suffix}@example.com",
        password_hash="not-a-real-password-hash",
        full_name="Test Analyst",
        role=UserRole.ANALYST,
    )
    session.add(user)
    session.flush()
    return user


def _customer(session: Session, suffix: str = "1") -> Customer:
    customer = Customer(
        customer_reference=f"CUST-{suffix}",
        first_name="Test",
        last_name="Customer",
        country_code="US",
        onboarding_date=date(2025, 1, 1),
    )
    session.add(customer)
    session.flush()
    return customer


def _account(
    session: Session,
    customer: Customer,
    suffix: str = "1",
) -> Account:
    account = Account(
        account_number=f"ACC-{suffix}",
        customer_id=customer.id,
        account_type=AccountType.CHECKING,
        currency=CurrencyCode.USD,
        status=AccountStatus.ACTIVE,
        balance=Decimal("100.00"),
        overdraft_limit=Decimal("0.00"),
        opened_at=utc_now(),
    )
    session.add(account)
    session.flush()
    return account


def _transaction(
    session: Session,
    account: Account,
    suffix: str = "1",
) -> Transaction:
    transaction = Transaction(
        transaction_reference=f"TX-{suffix}",
        debit_account_id=account.id,
        transaction_type=TransactionType.OUTGOING,
        status=TransactionStatus.POSTED,
        amount=Decimal("10.00"),
        currency=CurrencyCode.USD,
        occurred_at=utc_now(),
        debit_account_status_snapshot=AccountStatus.ACTIVE,
    )
    session.add(transaction)
    session.flush()
    return transaction


def _risk_rule(session: Session, suffix: str = "1") -> RiskRule:
    rule = RiskRule(
        code=f"RULE-{suffix}",
        version=1,
        name=f"Test rule {suffix}",
        category="test",
        severity=RiskSeverity.HIGH,
        score_weight=10,
        configuration={},
    )
    session.add(rule)
    session.flush()
    return rule


def _assessment(
    session: Session,
    transaction: Transaction,
    suffix: str = "1",
) -> RiskAssessment:
    assessment = RiskAssessment(
        transaction_id=transaction.id,
        model_version=f"model-{suffix}",
        score=50,
        risk_level=RiskLevel.HIGH,
        status=AssessmentStatus.COMPLETED,
    )
    session.add(assessment)
    session.flush()
    return assessment


def _finding(
    session: Session,
    assessment: RiskAssessment,
    rule: RiskRule,
) -> RiskFinding:
    finding = RiskFinding(
        assessment_id=assessment.id,
        rule_id=rule.id,
        rule_code=rule.code,
        score=50,
        severity=RiskSeverity.HIGH,
        explanation="Test finding",
    )
    session.add(finding)
    session.flush()
    return finding


def _alert(
    session: Session,
    transaction: Transaction,
    assessment: RiskAssessment,
    finding: RiskFinding,
    rule: RiskRule,
    suffix: str = "1",
) -> Alert:
    alert = Alert(
        alert_reference=f"ALERT-{suffix}",
        transaction_id=transaction.id,
        assessment_id=assessment.id,
        finding_id=finding.id,
        triggering_rule_id=rule.id,
        status=AlertStatus.OPEN,
        priority=AlertPriority.HIGH,
        score=50,
        summary="Test alert",
    )
    session.add(alert)
    session.flush()
    return alert


def _case(session: Session, user: User, suffix: str = "1") -> Case:
    case = Case(
        case_reference=f"CASE-{suffix}",
        title=f"Test case {suffix}",
        status=CaseStatus.OPEN,
        priority=CasePriority.MEDIUM,
        opened_by_user_id=user.id,
    )
    session.add(case)
    session.flush()
    return case


def test_foreign_key_rejects_missing_customer(schema_engine):
    with Session(schema_engine) as session:
        session.add(
            Account(
                account_number="ACC-ORPHAN",
                customer_id=999,
                account_type=AccountType.CHECKING,
                currency=CurrencyCode.USD,
                status=AccountStatus.ACTIVE,
                balance=Decimal("0.00"),
                overdraft_limit=Decimal("0.00"),
                opened_at=utc_now(),
            )
        )

        with pytest.raises(IntegrityError):
            session.commit()


def test_risk_assessment_is_unique_per_transaction_and_model_version(schema_engine):
    with Session(schema_engine) as session:
        customer = _customer(session)
        account = _account(session, customer)
        transaction = _transaction(session, account)
        assessment = _assessment(session, transaction)
        session.commit()

        session.add(
            RiskAssessment(
                transaction_id=assessment.transaction_id,
                model_version=assessment.model_version,
                score=60,
                risk_level=RiskLevel.HIGH,
                status=AssessmentStatus.COMPLETED,
            )
        )

        with pytest.raises(IntegrityError):
            session.commit()


def test_risk_finding_is_unique_per_assessment_and_rule(schema_engine):
    with Session(schema_engine) as session:
        customer = _customer(session)
        account = _account(session, customer)
        transaction = _transaction(session, account)
        rule = _risk_rule(session)
        assessment = _assessment(session, transaction)
        _finding(session, assessment, rule)
        session.commit()

        session.add(
            RiskFinding(
                assessment_id=assessment.id,
                rule_id=rule.id,
                rule_code=rule.code,
                score=40,
                severity=RiskSeverity.MEDIUM,
                explanation="Duplicate rule finding",
            )
        )

        with pytest.raises(IntegrityError):
            session.commit()


def test_alert_is_unique_per_finding(schema_engine):
    with Session(schema_engine) as session:
        customer = _customer(session)
        account = _account(session, customer)
        transaction = _transaction(session, account)
        rule = _risk_rule(session)
        assessment = _assessment(session, transaction)
        finding = _finding(session, assessment, rule)
        _alert(session, transaction, assessment, finding, rule)
        session.commit()

        session.add(
            Alert(
                alert_reference="ALERT-DUPLICATE",
                transaction_id=transaction.id,
                assessment_id=assessment.id,
                finding_id=finding.id,
                triggering_rule_id=rule.id,
                status=AlertStatus.OPEN,
                priority=AlertPriority.HIGH,
                score=50,
                summary="Duplicate alert for finding",
            )
        )

        with pytest.raises(IntegrityError):
            session.commit()


def test_case_alert_allows_only_one_active_link_per_alert(schema_engine):
    with Session(schema_engine) as session:
        user = _user(session)
        customer = _customer(session)
        account = _account(session, customer)
        transaction = _transaction(session, account)
        rule = _risk_rule(session)
        assessment = _assessment(session, transaction)
        finding = _finding(session, assessment, rule)
        alert = _alert(session, transaction, assessment, finding, rule)
        first_case = _case(session, user, "1")
        second_case = _case(session, user, "2")
        session.add(
            CaseAlert(
                case_id=first_case.id,
                alert_id=alert.id,
                linked_by_user_id=user.id,
            )
        )
        session.commit()

        session.add(
            CaseAlert(
                case_id=second_case.id,
                alert_id=alert.id,
                linked_by_user_id=user.id,
            )
        )

        with pytest.raises(IntegrityError):
            session.commit()


def test_ground_truth_is_unique_per_run_and_transaction(schema_engine):
    with Session(schema_engine) as session:
        session.add(
            GroundTruth(
                ground_truth_reference="GT-1",
                dataset_run_reference="RUN-1",
                transaction_reference="TX-1",
                is_fraud=False,
            )
        )
        session.commit()

        session.add(
            GroundTruth(
                ground_truth_reference="GT-2",
                dataset_run_reference="RUN-1",
                transaction_reference="TX-1",
                is_fraud=True,
                primary_pattern="STRUCTURING",
            )
        )

        with pytest.raises(IntegrityError):
            session.commit()


def test_append_only_records_reject_updates(schema_engine):
    with Session(schema_engine) as session:
        user = _user(session)
        customer = _customer(session)
        account = _account(session, customer)
        transaction = _transaction(session, account)
        rule = _risk_rule(session)
        assessment = _assessment(session, transaction)
        finding = _finding(session, assessment, rule)
        alert = _alert(session, transaction, assessment, finding, rule)
        case = _case(session, user)
        history = AccountStatusHistory(
            account_id=account.id,
            previous_status=AccountStatus.ACTIVE,
            new_status=AccountStatus.FROZEN,
            changed_by_user_id=user.id,
        )
        decision = CaseDecision(
            case_id=case.id,
            decided_by_user_id=user.id,
            decision=CaseDecisionType.MONITOR,
            rationale="Initial decision",
            triggering_alert_id=alert.id,
        )
        audit_event = AuditEvent(
            event_type="TEST",
            entity_type="case",
            entity_id=case.id,
            summary="Test audit event",
        )
        session.add_all([history, decision, audit_event])
        session.commit()

        for record, mutate in (
            (history, lambda item: setattr(item, "reason", "Changed reason")),
            (decision, lambda item: setattr(item, "rationale", "Changed rationale")),
            (audit_event, lambda item: setattr(item, "summary", "Changed summary")),
        ):
            mutate(record)
            with pytest.raises(AppendOnlyError):
                session.commit()
            session.rollback()


def test_append_only_records_reject_deletes(schema_engine):
    with Session(schema_engine) as session:
        audit_event = AuditEvent(
            event_type="TEST",
            entity_type="case",
            entity_id=1,
            summary="Delete-protected audit event",
        )
        session.add(audit_event)
        session.commit()

        session.delete(audit_event)

        with pytest.raises(AppendOnlyError):
            session.commit()
        session.rollback()
