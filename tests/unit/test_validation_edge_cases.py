"""Tests for the five mandatory validation edge cases."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from validation_factories import (
    BASE_TIME,
    make_account,
    make_alert,
    make_assessment,
    make_case,
    make_case_alert,
    make_case_decision,
    make_customer,
    make_finding,
    make_rule,
    make_transaction,
    make_transfer_group,
    make_user,
)

from app.models import Alert, ValidationEvent
from app.models.enums import (
    AccountStatus,
    AlertPriority,
    AlertStatus,
    TransactionType,
)
from app.services.validation import (
    ValidationError,
    validate_account_balance,
    validate_alert,
    validate_case_decision,
    validate_transaction,
    validate_transfer_group,
)


def _event_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(ValidationEvent)) or 0


def _latest_event(session: Session) -> ValidationEvent:
    event = session.scalar(
        select(ValidationEvent).order_by(ValidationEvent.id.desc()).limit(1)
    )
    assert event is not None
    return event


def test_transaction_referencing_closed_account_is_rejected_and_recorded(
    schema_engine,
):
    with Session(schema_engine) as session:
        customer = make_customer(session)
        account = make_account(session, customer, status=AccountStatus.CLOSED)
        transaction = make_transaction(
            session,
            debit_account=account,
            occurred_at=BASE_TIME + timedelta(hours=1),
        )

        with pytest.raises(ValidationError) as error:
            validate_transaction(session, transaction)

        assert error.value.issue.code == "TRANSACTION_CLOSED_ACCOUNT"
        session.commit()

        event = _latest_event(session)
        assert _event_count(session) == 1
        assert event.validation_code == "TRANSACTION_CLOSED_ACCOUNT"
        assert event.entity_type == "transaction"
        assert event.entity_id == transaction.id
        assert event.transaction_id == transaction.id


def test_negative_balance_without_overdraft_is_rejected_and_recorded(schema_engine):
    with Session(schema_engine) as session:
        customer = make_customer(session)
        account = make_account(session, customer)

        with pytest.raises(ValidationError) as error:
            validate_account_balance(
                session,
                Decimal("-0.01"),
                Decimal("0.00"),
                entity_id=account.id,
            )

        assert error.value.issue.code == "NEGATIVE_BALANCE_WITHOUT_OVERDRAFT"
        session.commit()

        event = _latest_event(session)
        assert _event_count(session) == 1
        assert event.validation_code == "NEGATIVE_BALANCE_WITHOUT_OVERDRAFT"
        assert event.entity_type == "account"
        assert event.entity_id == account.id


def test_negative_balance_within_overdraft_is_allowed(schema_engine):
    with Session(schema_engine) as session:
        customer = make_customer(session)
        account = make_account(session, customer)

        validate_account_balance(
            session,
            Decimal("-50.00"),
            Decimal("100.00"),
            entity_id=account.id,
        )
        session.commit()

        assert _event_count(session) == 0


def test_transfer_legs_that_do_not_reconcile_are_rejected_and_recorded(
    schema_engine,
):
    with Session(schema_engine) as session:
        customer = make_customer(session)
        source = make_account(session, customer)
        destination = make_account(session, customer)
        group = make_transfer_group(
            session,
            customer,
            add=False,
            expected_total=Decimal("100.00"),
            actual_total=Decimal("90.00"),
        )
        leg = make_transaction(
            session,
            add=False,
            debit_account=source,
            credit_account=destination,
            transaction_type=TransactionType.INTERNAL,
            amount=Decimal("100.00"),
        )

        with pytest.raises(ValidationError) as error:
            validate_transfer_group(session, group, [leg])

        assert error.value.issue.code == "TRANSFER_TOTALS_MISMATCH"
        session.commit()

        event = _latest_event(session)
        assert _event_count(session) == 1
        assert event.validation_code == "TRANSFER_TOTALS_MISMATCH"
        assert event.entity_type == "transfer_group"


def test_alert_without_triggering_transaction_is_rejected_and_recorded(
    schema_engine,
):
    with Session(schema_engine) as session:
        customer = make_customer(session)
        account = make_account(session, customer)
        transaction = make_transaction(session, debit_account=account)
        rule = make_rule(session)
        assessment = make_assessment(session, transaction)
        finding = make_finding(session, assessment, rule)
        alert = Alert(
            alert_reference="ALERT-NO-TRANSACTION",
            transaction_id=None,
            assessment_id=assessment.id,
            finding_id=finding.id,
            triggering_rule_id=rule.id,
            status=AlertStatus.OPEN,
            priority=AlertPriority.HIGH,
            score=50,
            summary="Alert without transaction",
            created_at=BASE_TIME + timedelta(hours=3),
        )

        with pytest.raises(ValidationError) as error:
            validate_alert(session, alert)

        assert error.value.issue.code == "ALERT_MISSING_TRANSACTION"
        session.commit()

        event = _latest_event(session)
        assert _event_count(session) == 1
        assert event.validation_code == "ALERT_MISSING_TRANSACTION"
        assert event.entity_type == "alert"


def test_alert_without_triggering_transaction_is_prevented_by_database(
    schema_engine,
):
    with Session(schema_engine) as session:
        customer = make_customer(session)
        account = make_account(session, customer)
        transaction = make_transaction(session, debit_account=account)
        rule = make_rule(session)
        assessment = make_assessment(session, transaction)
        finding = make_finding(session, assessment, rule)
        session.add(
            Alert(
                alert_reference="ALERT-DB-NO-TRANSACTION",
                transaction_id=None,
                assessment_id=assessment.id,
                finding_id=finding.id,
                triggering_rule_id=rule.id,
                status=AlertStatus.OPEN,
                priority=AlertPriority.HIGH,
                score=50,
                summary="Database must reject this alert",
            )
        )

        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_case_decision_before_alert_creation_is_rejected_and_recorded(
    schema_engine,
):
    with Session(schema_engine) as session:
        user = make_user(session)
        customer = make_customer(session)
        account = make_account(session, customer)
        transaction = make_transaction(session, debit_account=account)
        rule = make_rule(session)
        assessment = make_assessment(session, transaction)
        finding = make_finding(session, assessment, rule)
        alert = make_alert(session, transaction, assessment, finding, rule)
        case = make_case(session, user)
        make_case_alert(session, case, alert, user)
        decision = make_case_decision(
            session,
            case,
            user,
            alert,
            add=False,
            decided_at=BASE_TIME + timedelta(hours=2),
        )

        with pytest.raises(ValidationError) as error:
            validate_case_decision(session, decision)

        assert error.value.issue.code == "CASE_DECISION_BEFORE_ALERT"
        session.commit()

        event = _latest_event(session)
        assert _event_count(session) == 1
        assert event.validation_code == "CASE_DECISION_BEFORE_ALERT"
        assert event.entity_type == "case_decision"
