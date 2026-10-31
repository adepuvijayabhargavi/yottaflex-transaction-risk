"""Valid and invalid cases for the validation services."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from validation_factories import (
    BASE_TIME,
    make_account,
    make_alert,
    make_assessment,
    make_audit_event,
    make_case,
    make_case_alert,
    make_case_decision,
    make_case_note,
    make_customer,
    make_dataset_run,
    make_device,
    make_finding,
    make_merchant,
    make_rule,
    make_transaction,
    make_transfer_group,
    make_user,
    make_validation_event,
)

from app.models import AccountStatusHistory, User, ValidationEvent
from app.models.enums import (
    AccountStatus,
    CurrencyCode,
    TransactionType,
    TransferStatus,
    ValidationResolutionStatus,
)
from app.services.validation import (
    ValidationError,
    validate_account,
    validate_account_balance,
    validate_account_status_history,
    validate_account_status_transition,
    validate_alert,
    validate_audit_event,
    validate_case,
    validate_case_alert,
    validate_case_decision,
    validate_case_note,
    validate_customer,
    validate_dataset_run,
    validate_device,
    validate_merchant,
    validate_primary_key_reference,
    validate_risk_assessment,
    validate_risk_finding,
    validate_risk_rule,
    validate_transaction,
    validate_transfer_group,
    validate_user,
    validate_validation_event,
)


def _event_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(ValidationEvent)) or 0


def _latest_event(session: Session) -> ValidationEvent:
    event = session.scalar(
        select(ValidationEvent).order_by(ValidationEvent.id.desc()).limit(1)
    )
    assert event is not None
    return event


def _assert_recorded(session: Session, code: str, entity_type: str) -> None:
    session.commit()
    assert _event_count(session) == 1
    event = _latest_event(session)
    assert event.validation_code == code
    assert event.entity_type == entity_type


def test_valid_core_entities_pass_validation(schema_engine):
    with Session(schema_engine) as session:
        user = make_user(session)
        customer = make_customer(session)
        merchant = make_merchant(session)
        device = make_device(session, customer)
        source = make_account(session, customer)
        destination = make_account(session, customer)
        history = AccountStatusHistory(
            account_id=source.id,
            previous_status=AccountStatus.ACTIVE,
            new_status=AccountStatus.FROZEN,
            changed_by_user_id=user.id,
            changed_at=BASE_TIME + timedelta(hours=1),
        )
        session.add(history)
        session.flush()

        transfer = make_transfer_group(session, customer)
        leg_one = make_transaction(
            session,
            debit_account=source,
            credit_account=destination,
            transaction_type=TransactionType.INTERNAL,
            amount=Decimal("50.00"),
            transfer_group_id=transfer.id,
        )
        leg_two = make_transaction(
            session,
            debit_account=destination,
            credit_account=source,
            transaction_type=TransactionType.INTERNAL,
            amount=Decimal("50.00"),
            transfer_group_id=transfer.id,
        )
        transaction = make_transaction(
            session,
            debit_account=source,
            merchant_id=merchant.id,
            device_id=device.id,
        )
        rule = make_rule(session)
        assessment = make_assessment(session, transaction)
        finding = make_finding(session, assessment, rule)
        alert = make_alert(session, transaction, assessment, finding, rule)
        case = make_case(session, user)
        link = make_case_alert(session, case, alert, user)
        note = make_case_note(session, case, user)
        decision = make_case_decision(session, case, user, alert)
        run = make_dataset_run(session)
        event = make_validation_event(session)
        audit = make_audit_event(session, actor_user_id=user.id)
        baseline_events = _event_count(session)

        validate_user(session, user)
        validate_customer(session, customer)
        validate_merchant(session, merchant)
        validate_device(session, device)
        validate_account(session, source)
        validate_account(session, destination)
        validate_account_status_history(session, history)
        validate_transfer_group(session, transfer, [leg_one, leg_two])
        validate_transaction(session, transaction)
        validate_transaction(session, leg_one)
        validate_transaction(session, leg_two)
        validate_risk_rule(session, rule)
        validate_risk_assessment(session, assessment)
        validate_risk_finding(session, finding)
        validate_alert(session, alert)
        validate_case(session, case)
        validate_case_alert(session, link)
        validate_case_note(session, note)
        validate_case_decision(session, decision)
        validate_dataset_run(session, run)
        validate_validation_event(session, event)
        validate_audit_event(session, audit)
        validate_primary_key_reference(session, User, user.id, entity_type="user")

        session.commit()
        events = list(session.scalars(select(ValidationEvent)))
        assert _event_count(session) == baseline_events, [
            (event.validation_code, event.entity_type, event.entity_id)
            for event in events
        ]


def test_validate_user_rejects_blank_username(schema_engine):
    with Session(schema_engine) as session:
        user = make_user(session, add=False)
        user.username = " "

        with pytest.raises(ValidationError) as error:
            validate_user(session, user)

        assert error.value.issue.code == "MISSING_REQUIRED_FIELD"
        _assert_recorded(session, "MISSING_REQUIRED_FIELD", "user")


def test_validate_customer_rejects_invalid_country(schema_engine):
    with Session(schema_engine) as session:
        customer = make_customer(session, add=False)
        customer.country_code = "USA"

        with pytest.raises(ValidationError) as error:
            validate_customer(session, customer)

        assert error.value.issue.code == "INVALID_COUNTRY_CODE"
        _assert_recorded(session, "INVALID_COUNTRY_CODE", "customer")


def test_validate_device_rejects_reversed_seen_times(schema_engine):
    with Session(schema_engine) as session:
        customer = make_customer(session)
        device = make_device(
            session,
            customer,
            add=False,
            first_seen_at=BASE_TIME + timedelta(hours=2),
            last_seen_at=BASE_TIME + timedelta(hours=1),
        )

        with pytest.raises(ValidationError) as error:
            validate_device(session, device)

        assert error.value.issue.code == "INVALID_TIMESTAMP_ORDER"
        _assert_recorded(session, "INVALID_TIMESTAMP_ORDER", "device")


def test_validate_account_status_transition_rejects_closed_to_active(
    schema_engine,
):
    with Session(schema_engine) as session:
        with pytest.raises(ValidationError) as error:
            validate_account_status_transition(
                session,
                AccountStatus.CLOSED,
                AccountStatus.ACTIVE,
                entity_id=1,
            )

        assert error.value.issue.code == "ACCOUNT_STATUS_TRANSITION_INVALID"
        _assert_recorded(
            session,
            "ACCOUNT_STATUS_TRANSITION_INVALID",
            "account",
        )


def test_validate_account_rejects_closed_timestamp_mismatch(schema_engine):
    with Session(schema_engine) as session:
        customer = make_customer(session)
        account = make_account(
            session,
            customer,
            add=False,
            status=AccountStatus.ACTIVE,
            closed_at=BASE_TIME + timedelta(hours=1),
        )

        with pytest.raises(ValidationError) as error:
            validate_account(session, account)

        assert error.value.issue.code == "CLOSED_TIMESTAMP_MISMATCH"
        _assert_recorded(session, "CLOSED_TIMESTAMP_MISMATCH", "account")


def test_validate_account_balance_rejects_amount_beyond_overdraft(schema_engine):
    with Session(schema_engine) as session:
        with pytest.raises(ValidationError) as error:
            validate_account_balance(
                session,
                Decimal("-100.01"),
                Decimal("100.00"),
                entity_id=1,
            )

        assert error.value.issue.code == "BALANCE_EXCEEDS_OVERDRAFT"
        _assert_recorded(session, "BALANCE_EXCEEDS_OVERDRAFT", "account")


def test_validate_transaction_rejects_currency_mismatch(schema_engine):
    with Session(schema_engine) as session:
        customer = make_customer(session)
        account = make_account(session, customer)
        transaction = make_transaction(
            session,
            add=False,
            debit_account=account,
            currency=CurrencyCode.EUR,
        )

        with pytest.raises(ValidationError) as error:
            validate_transaction(session, transaction)

        assert error.value.issue.code == "TRANSACTION_CURRENCY_MISMATCH"
        _assert_recorded(session, "TRANSACTION_CURRENCY_MISMATCH", "transaction")


def test_validate_transfer_group_rejects_leg_currency_mismatch(schema_engine):
    with Session(schema_engine) as session:
        customer = make_customer(session)
        source = make_account(session, customer)
        destination = make_account(session, customer)
        group = make_transfer_group(
            session,
            customer,
            add=False,
            status=TransferStatus.PENDING,
            actual_total=Decimal("0.00"),
        )
        leg = make_transaction(
            session,
            add=False,
            debit_account=source,
            credit_account=destination,
            transaction_type=TransactionType.INTERNAL,
            currency=CurrencyCode.EUR,
        )

        with pytest.raises(ValidationError) as error:
            validate_transfer_group(session, group, [leg])

        assert error.value.issue.code == "TRANSFER_CURRENCY_MISMATCH"
        _assert_recorded(session, "TRANSFER_CURRENCY_MISMATCH", "transfer_group")


def test_validate_risk_rule_rejects_score_weight(schema_engine):
    with Session(schema_engine) as session:
        rule = make_rule(session, add=False)
        rule.score_weight = 101

        with pytest.raises(ValidationError) as error:
            validate_risk_rule(session, rule)

        assert error.value.issue.code == "INVALID_SCORE_WEIGHT"
        _assert_recorded(session, "INVALID_SCORE_WEIGHT", "risk_rule")


def test_validate_risk_assessment_rejects_score_out_of_range(schema_engine):
    with Session(schema_engine) as session:
        customer = make_customer(session)
        account = make_account(session, customer)
        transaction = make_transaction(session, debit_account=account)
        assessment = make_assessment(session, transaction, add=False, score=101)

        with pytest.raises(ValidationError) as error:
            validate_risk_assessment(session, assessment)

        assert error.value.issue.code == "VALUE_OUT_OF_RANGE"
        _assert_recorded(session, "VALUE_OUT_OF_RANGE", "risk_assessment")


def test_validate_risk_finding_rejects_rule_code_mismatch(schema_engine):
    with Session(schema_engine) as session:
        customer = make_customer(session)
        account = make_account(session, customer)
        transaction = make_transaction(session, debit_account=account)
        rule = make_rule(session)
        assessment = make_assessment(session, transaction)
        finding = make_finding(
            session,
            assessment,
            rule,
            add=False,
            rule_code="OTHER-RULE",
        )

        with pytest.raises(ValidationError) as error:
            validate_risk_finding(session, finding)

        assert error.value.issue.code == "FINDING_RULE_CODE_MISMATCH"
        _assert_recorded(session, "FINDING_RULE_CODE_MISMATCH", "risk_finding")


def test_validate_alert_rejects_inconsistent_rule_reference(schema_engine):
    with Session(schema_engine) as session:
        customer = make_customer(session)
        account = make_account(session, customer)
        transaction = make_transaction(session, debit_account=account)
        rule = make_rule(session)
        other_rule = make_rule(session)
        assessment = make_assessment(session, transaction)
        finding = make_finding(session, assessment, rule)
        alert = make_alert(
            session,
            transaction,
            assessment,
            finding,
            rule,
            add=False,
        )
        alert.triggering_rule_id = other_rule.id

        with pytest.raises(ValidationError) as error:
            validate_alert(session, alert)

        assert error.value.issue.code == "ALERT_REFERENCE_MISMATCH"
        _assert_recorded(session, "ALERT_REFERENCE_MISMATCH", "alert")


def test_validate_case_rejects_invalid_status(schema_engine):
    with Session(schema_engine) as session:
        user = make_user(session)
        case = make_case(session, user, add=False, status="NOT_A_STATUS")

        with pytest.raises(ValidationError) as error:
            validate_case(session, case)

        assert error.value.issue.code == "INVALID_ENUM_VALUE"
        _assert_recorded(session, "INVALID_ENUM_VALUE", "case")


def test_validate_case_rejects_missing_closed_timestamp(schema_engine):
    with Session(schema_engine) as session:
        user = make_user(session)
        case = make_case(session, user, add=False, status="CLOSED")

        with pytest.raises(ValidationError) as error:
            validate_case(session, case)

        assert error.value.issue.code == "CLOSED_TIMESTAMP_MISMATCH"
        _assert_recorded(session, "CLOSED_TIMESTAMP_MISMATCH", "case")


def test_validate_case_alert_rejects_unlink_without_actor(schema_engine):
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
        link = make_case_alert(
            session,
            case,
            alert,
            user,
            add=False,
            unlinked_at=BASE_TIME + timedelta(hours=6),
        )

        with pytest.raises(ValidationError) as error:
            validate_case_alert(session, link)

        assert error.value.issue.code == "CASE_ALERT_UNLINK_MISSING_ACTOR"
        _assert_recorded(
            session,
            "CASE_ALERT_UNLINK_MISSING_ACTOR",
            "case_alert",
        )


def test_validate_case_note_rejects_blank_body(schema_engine):
    with Session(schema_engine) as session:
        user = make_user(session)
        case = make_case(session, user)
        note = make_case_note(session, case, user, add=False, body=" ")

        with pytest.raises(ValidationError) as error:
            validate_case_note(session, note)

        assert error.value.issue.code == "MISSING_REQUIRED_FIELD"
        _assert_recorded(session, "MISSING_REQUIRED_FIELD", "case_note")


def test_validate_dataset_run_rejects_reversed_timestamps(schema_engine):
    with Session(schema_engine) as session:
        run = make_dataset_run(
            session,
            add=False,
            started_at=BASE_TIME + timedelta(hours=1),
            completed_at=BASE_TIME,
        )

        with pytest.raises(ValidationError) as error:
            validate_dataset_run(session, run)

        assert error.value.issue.code == "INVALID_TIMESTAMP_ORDER"
        _assert_recorded(session, "INVALID_TIMESTAMP_ORDER", "dataset_run")


def test_validate_validation_event_rejects_open_event_with_resolution(
    schema_engine,
):
    with Session(schema_engine) as session:
        event = make_validation_event(
            session,
            add=False,
            resolution_status=ValidationResolutionStatus.OPEN,
            resolved_at=BASE_TIME + timedelta(hours=1),
        )

        with pytest.raises(ValidationError) as error:
            validate_validation_event(session, event)

        assert error.value.issue.code == "VALIDATION_RESOLUTION_MISMATCH"
        _assert_recorded(
            session,
            "VALIDATION_RESOLUTION_MISMATCH",
            "validation_event",
        )


def test_validate_validation_event_rejects_resolved_without_timestamp(
    schema_engine,
):
    with Session(schema_engine) as session:
        event = make_validation_event(
            session,
            add=False,
            resolution_status=ValidationResolutionStatus.RESOLVED,
        )

        with pytest.raises(ValidationError) as error:
            validate_validation_event(session, event)

        assert error.value.issue.code == "VALIDATION_RESOLUTION_MISMATCH"
        _assert_recorded(
            session,
            "VALIDATION_RESOLUTION_MISMATCH",
            "validation_event",
        )


def test_validate_audit_event_rejects_blank_summary(schema_engine):
    with Session(schema_engine) as session:
        event = make_audit_event(session, add=False)
        event.summary = " "

        with pytest.raises(ValidationError) as error:
            validate_audit_event(session, event)

        assert error.value.issue.code == "MISSING_REQUIRED_FIELD"
        _assert_recorded(session, "MISSING_REQUIRED_FIELD", "audit_event")


def test_validate_primary_key_reference_rejects_missing_record(schema_engine):
    with Session(schema_engine) as session:
        with pytest.raises(ValidationError) as error:
            validate_primary_key_reference(
                session,
                User,
                999_999,
                entity_type="user",
            )

        assert error.value.issue.code == "REFERENCE_NOT_FOUND"
        _assert_recorded(session, "REFERENCE_NOT_FOUND", "user")


def test_validation_can_skip_event_recording(schema_engine):
    with Session(schema_engine) as session:
        user = make_user(session, add=False)
        user.username = " "

        with pytest.raises(ValidationError):
            validate_user(session, user, record_event=False)

        session.commit()
        assert _event_count(session) == 0
