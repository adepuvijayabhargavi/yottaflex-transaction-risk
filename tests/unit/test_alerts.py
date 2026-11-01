"""Alert queue and review workflow tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app import create_app
from app.blueprints.alerts.routes import _execute_alert_action
from app.extensions import db
from app.models import (
    Account,
    Alert,
    AuditEvent,
    Base,
    Customer,
    RiskAssessment,
    RiskFinding,
    RiskRule,
    Transaction,
    User,
)
from app.models.base import utc_now
from app.models.enums import (
    AccountStatus,
    AccountType,
    AlertPriority,
    AlertStatus,
    AssessmentStatus,
    CurrencyCode,
    RiskLevel,
    RiskSeverity,
    TransactionStatus,
    TransactionType,
    UserRole,
)
from app.services.alerts import (
    acknowledge_alert,
    assign_alert,
    close_alert,
    dismiss_alert,
)
from app.services.validation import ValidationError


@pytest.fixture()
def alerts_app():
    test_app = create_app("testing")
    with test_app.app_context():
        Base.metadata.create_all(db.engine)
        yield test_app
        db.session.remove()
        Base.metadata.drop_all(db.engine)


@pytest.fixture()
def alerts_client(alerts_app):
    return alerts_app.test_client()


def _create_user(
    suffix: str,
    *,
    role: UserRole = UserRole.ANALYST,
    active: bool = True,
) -> User:
    user = User(
        username=f"reviewer_{suffix}",
        email=f"reviewer_{suffix}@yottaflex.bank",
        full_name=f"Reviewer {suffix}",
        role=role,
        is_active=active,
    )
    user.set_password("SecurePassword123!")
    db.session.add(user)
    db.session.flush()
    return user


def _create_alert():
    now = utc_now()
    actor = _create_user("actor")
    assignee = _create_user("assignee", role=UserRole.SUPERVISOR)
    inactive_user = _create_user("inactive", active=False)

    customer = Customer(
        customer_reference="CUST-ALERT-1",
        first_name="Test",
        last_name="Customer",
        country_code="US",
        onboarding_date=date(2025, 1, 1),
    )
    db.session.add(customer)
    db.session.flush()

    account = Account(
        account_number="ACC-ALERT-1",
        customer_id=customer.id,
        account_type=AccountType.CHECKING,
        currency=CurrencyCode.USD,
        status=AccountStatus.ACTIVE,
        balance=Decimal("1000.00"),
        overdraft_limit=Decimal("0.00"),
        opened_at=now,
    )
    db.session.add(account)
    db.session.flush()

    rule = RiskRule(
        code="ALERT_TEST_RULE",
        version=1,
        name="Alert test rule",
        category="TEST",
        severity=RiskSeverity.HIGH,
        score_weight=50,
        configuration={},
        is_active=True,
        effective_from=now,
    )
    db.session.add(rule)
    db.session.flush()

    transaction = Transaction(
        transaction_reference="TX-ALERT-1",
        debit_account_id=account.id,
        transaction_type=TransactionType.OUTGOING,
        status=TransactionStatus.POSTED,
        amount=Decimal("100.00"),
        currency=CurrencyCode.USD,
        occurred_at=now,
        debit_account_status_snapshot=AccountStatus.ACTIVE,
    )
    db.session.add(transaction)
    db.session.flush()

    assessment = RiskAssessment(
        transaction_id=transaction.id,
        model_version="test-v1",
        score=75,
        risk_level=RiskLevel.HIGH,
        status=AssessmentStatus.COMPLETED,
        assessed_at=now,
    )
    db.session.add(assessment)
    db.session.flush()

    finding = RiskFinding(
        assessment_id=assessment.id,
        rule_id=rule.id,
        rule_code=rule.code,
        score=50,
        severity=RiskSeverity.HIGH,
        explanation="Test finding",
    )
    db.session.add(finding)
    db.session.flush()

    alert = Alert(
        alert_reference="ALT-TEST-1",
        transaction_id=transaction.id,
        assessment_id=assessment.id,
        finding_id=finding.id,
        triggering_rule_id=rule.id,
        status=AlertStatus.OPEN,
        priority=AlertPriority.HIGH,
        score=75,
        summary="Test alert",
    )
    db.session.add(alert)
    db.session.commit()
    return actor, assignee, inactive_user, alert


def test_assign_and_unassign_alert_audit_each_change(alerts_app):
    with alerts_app.app_context():
        actor, assignee, _, alert = _create_alert()

        assign_alert(db.session, alert.id, actor, assignee.id)
        db.session.commit()
        assert db.session.get(Alert, alert.id).assigned_to_user_id == assignee.id

        assign_alert(db.session, alert.id, actor, None)
        db.session.commit()
        assert db.session.get(Alert, alert.id).assigned_to_user_id is None

        events = db.session.scalars(
            db.select(AuditEvent)
            .where(AuditEvent.entity_type == "alert", AuditEvent.entity_id == alert.id)
            .order_by(AuditEvent.id)
        ).all()
        assert [event.event_type for event in events] == [
            "ALERT_ASSIGNED",
            "ALERT_UNASSIGNED",
        ]
        assert events[0].actor_user_id == actor.id
        assert events[0].details == {
            "previous_assignee_user_id": None,
            "assignee_user_id": assignee.id,
        }
        assert events[1].details == {
            "previous_assignee_user_id": assignee.id,
            "assignee_user_id": None,
        }


def test_assignment_rejects_inactive_and_unchanged_assignees(alerts_app):
    with alerts_app.app_context():
        actor, assignee, inactive_user, alert = _create_alert()

        with pytest.raises(ValidationError, match="active analyst"):
            assign_alert(db.session, alert.id, actor, inactive_user.id)
        db.session.rollback()
        with pytest.raises(ValidationError, match="active analyst"):
            assign_alert(db.session, alert.id, actor, 99999)
        db.session.rollback()

        assign_alert(db.session, alert.id, actor, assignee.id)
        db.session.commit()
        with pytest.raises(ValidationError, match="already assigned"):
            assign_alert(db.session, alert.id, actor, assignee.id)

        terminal_alert = db.session.get(Alert, alert.id)
        terminal_alert.status = AlertStatus.CLOSED
        terminal_alert.closed_at = utc_now()
        db.session.commit()
        with pytest.raises(ValidationError, match="cannot be reassigned"):
            assign_alert(db.session, alert.id, actor, None)


def test_acknowledge_then_close_records_timestamps_and_reason(alerts_app):
    with alerts_app.app_context():
        actor, _, _, alert = _create_alert()

        acknowledge_alert(db.session, alert.id, actor)
        db.session.commit()
        acknowledged = db.session.get(Alert, alert.id)
        assert acknowledged.status == AlertStatus.ACKNOWLEDGED
        assert acknowledged.acknowledged_at is not None

        close_alert(db.session, alert.id, actor, "Investigation completed")
        db.session.commit()
        closed = db.session.get(Alert, alert.id)
        assert closed.status == AlertStatus.CLOSED
        assert closed.closed_at is not None
        assert closed.closed_at >= closed.acknowledged_at

        events = db.session.scalars(
            db.select(AuditEvent)
            .where(AuditEvent.entity_type == "alert", AuditEvent.entity_id == alert.id)
            .order_by(AuditEvent.id)
        ).all()
        assert [event.event_type for event in events] == [
            "ALERT_ACKNOWLEDGED",
            "ALERT_CLOSED",
        ]
        assert events[-1].details == {
            "previous_status": AlertStatus.ACKNOWLEDGED.value,
            "status": AlertStatus.CLOSED.value,
            "reason": "Investigation completed",
        }


def test_dismiss_requires_reason_and_is_terminal(alerts_app):
    with alerts_app.app_context():
        actor, _, _, alert = _create_alert()

        with pytest.raises(ValidationError, match="reason is required"):
            dismiss_alert(db.session, alert.id, actor, "  ")
        with pytest.raises(ValidationError, match="500 characters or fewer"):
            dismiss_alert(db.session, alert.id, actor, "x" * 501)

        dismiss_alert(db.session, alert.id, actor, "False positive")
        db.session.commit()
        dismissed = db.session.get(Alert, alert.id)
        assert dismissed.status == AlertStatus.DISMISSED
        assert dismissed.closed_at is not None

        with pytest.raises(ValidationError, match="Only an open or acknowledged"):
            close_alert(db.session, alert.id, actor, "Cannot reopen")


def test_alert_actions_are_authenticated_post_routes(alerts_app, alerts_client):
    with alerts_app.app_context():
        actor, assignee, _, alert = _create_alert()
        actor_username = actor.username
        alert_id = alert.id
        assignee_id = assignee.id

    unauthenticated = alerts_client.post(f"/alerts/{alert_id}/acknowledge")
    assert unauthenticated.status_code == 302
    assert "/login" in unauthenticated.headers["Location"]
    assert alerts_client.get(f"/alerts/{alert_id}/acknowledge").status_code == 405

    login_response = alerts_client.post(
        "/login",
        data={
            "username": actor_username,
            "password": "SecurePassword123!",
        },
    )
    assert login_response.status_code == 302

    detail_response = alerts_client.get(f"/alerts/{alert_id}")
    assert detail_response.status_code == 200
    assert b"Review actions enabled" in detail_response.data
    assert b"Acknowledge" in detail_response.data
    assert b"Close reason" in detail_response.data

    assigned = alerts_client.post(
        f"/alerts/{alert_id}/assign",
        data={"assignee_id": str(assignee_id)},
    )
    assert assigned.status_code == 302

    acknowledged = alerts_client.post(f"/alerts/{alert_id}/acknowledge")
    assert acknowledged.status_code == 302

    closed = alerts_client.post(
        f"/alerts/{alert_id}/close",
        data={"reason": "Reviewed in web workflow"},
    )
    assert closed.status_code == 302

    with alerts_app.app_context():
        updated = db.session.get(Alert, alert_id)
        assert updated.status == AlertStatus.CLOSED
        assert updated.assigned_to_user_id == assignee_id
        assert [
            event.event_type
            for event in db.session.scalars(
                db.select(AuditEvent)
                .where(
                    AuditEvent.entity_type == "alert",
                    AuditEvent.entity_id == alert_id,
                )
                .order_by(AuditEvent.id)
            ).all()
        ] == ["ALERT_ASSIGNED", "ALERT_ACKNOWLEDGED", "ALERT_CLOSED"]


def test_alert_action_requires_csrf_token(alerts_app, alerts_client):
    with alerts_app.app_context():
        _, _, _, alert = _create_alert()
        alert_id = alert.id
        alerts_app.config["WTF_CSRF_ENABLED"] = True

    response = alerts_client.post(f"/alerts/{alert_id}/acknowledge")
    assert response.status_code == 400


def test_assign_missing_alert_returns_404_before_assignee_validation(
    alerts_app,
    alerts_client,
):
    with alerts_app.app_context():
        actor, _, _, _ = _create_alert()
        actor_username = actor.username

    login_response = alerts_client.post(
        "/login",
        data={
            "username": actor_username,
            "password": "SecurePassword123!",
        },
    )
    assert login_response.status_code == 302

    response = alerts_client.post(
        "/alerts/99999/assign",
        data={"assignee_id": "not-an-integer"},
    )
    assert response.status_code == 404


def test_alert_action_rolls_back_and_reraises_database_commit_failure(
    alerts_app,
    monkeypatch,
):
    with alerts_app.app_context():
        actor, _, _, alert = _create_alert()
        alert_id = alert.id
        session = db.session()
        original_rollback = session.rollback
        rollback_calls = 0

        def fail_commit():
            raise SQLAlchemyError("simulated commit failure")

        def track_rollback():
            nonlocal rollback_calls
            rollback_calls += 1
            original_rollback()

        monkeypatch.setattr(session, "commit", fail_commit)
        monkeypatch.setattr(session, "rollback", track_rollback)

        with alerts_app.test_request_context(
            f"/alerts/{alert_id}/acknowledge"
        ), pytest.raises(SQLAlchemyError, match="simulated commit failure"):
            _execute_alert_action(
                alert_id,
                lambda: acknowledge_alert(session, alert_id, actor),
                "Alert acknowledged.",
            )

        assert rollback_calls == 1
        session.expire_all()
        persisted_alert = session.get(Alert, alert_id)
        assert persisted_alert.status == AlertStatus.OPEN
        assert persisted_alert.acknowledged_at is None
        assert (
            session.scalar(
                db.select(AuditEvent.id).where(
                    AuditEvent.entity_type == "alert",
                    AuditEvent.entity_id == alert_id,
                )
            )
            is None
        )
