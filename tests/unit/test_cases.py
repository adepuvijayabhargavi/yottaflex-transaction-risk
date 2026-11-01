"""Case queue and case workflow tests."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app import create_app
from app.blueprints.cases.routes import _execute_case_action
from app.extensions import db
from app.models import (
    Account,
    Alert,
    AuditEvent,
    Base,
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
    CaseNoteType,
    CasePriority,
    CaseStatus,
    CurrencyCode,
    RiskLevel,
    RiskSeverity,
    TransactionStatus,
    TransactionType,
    UserRole,
)
from app.services.cases import (
    add_case_decision,
    add_case_note,
    assign_case,
    claim_case,
    create_case,
    get_active_case_for_alert,
    get_case_detail,
    link_alert_to_case,
    list_cases,
    list_eligible_alerts,
    set_case_priority,
    transition_case,
    unlink_alert_from_case,
)
from app.services.validation import ValidationError


@pytest.fixture()
def cases_app():
    test_app = create_app("testing")
    with test_app.app_context():
        Base.metadata.create_all(db.engine)
    yield test_app
    with test_app.app_context():
        db.session.remove()
        Base.metadata.drop_all(db.engine)


def _create_user(suffix: str, role: UserRole = UserRole.ANALYST) -> User:
    user = User(
        username=f"case_{suffix}",
        email=f"case_{suffix}@yottaflex.bank",
        full_name=f"Case Reviewer {suffix}",
        role=role,
        is_active=True,
    )
    user.set_password("SecurePassword123!")
    db.session.add(user)
    db.session.flush()
    return user


def _seed_case_data():
    now = utc_now()
    analyst = _create_user("analyst")
    other_analyst = _create_user("other")
    supervisor = _create_user("supervisor", UserRole.SUPERVISOR)
    admin = _create_user("admin", UserRole.ADMIN)
    customer = Customer(
        customer_reference="CUST-CASE-1",
        first_name="Case",
        last_name="Customer",
        country_code="US",
        onboarding_date=now.date(),
    )
    db.session.add(customer)
    db.session.flush()
    account = Account(
        account_number="ACC-CASE-1",
        customer_id=customer.id,
        account_type=AccountType.CHECKING,
        currency=CurrencyCode.USD,
        status=AccountStatus.ACTIVE,
        balance=Decimal("1000.00"),
        overdraft_limit=Decimal("0.00"),
        opened_at=now - timedelta(days=1),
    )
    db.session.add(account)
    rule = RiskRule(
        code="CASE_TEST_RULE",
        version=1,
        name="Case test rule",
        category="TEST",
        severity=RiskSeverity.HIGH,
        score_weight=50,
        configuration={},
        is_active=True,
        effective_from=now - timedelta(days=1),
    )
    db.session.add(rule)
    db.session.flush()

    def make_alert(reference: str, status: AlertStatus = AlertStatus.OPEN) -> Alert:
        transaction = Transaction(
            transaction_reference=f"TX-{reference}",
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
            model_version="case-test-v1",
            score=70,
            risk_level=RiskLevel.HIGH,
            status=AssessmentStatus.COMPLETED,
            assessed_at=now,
            explanation={"summary": "Stored case test assessment"},
        )
        db.session.add(assessment)
        db.session.flush()
        finding = RiskFinding(
            assessment_id=assessment.id,
            rule_id=rule.id,
            rule_code=rule.code,
            score=50,
            severity=RiskSeverity.HIGH,
            explanation="Stored case test finding.",
            evidence={},
        )
        db.session.add(finding)
        db.session.flush()
        alert = Alert(
            alert_reference=reference,
            transaction_id=transaction.id,
            assessment_id=assessment.id,
            finding_id=finding.id,
            triggering_rule_id=rule.id,
            status=status,
            priority=AlertPriority.HIGH,
            score=70,
            summary=f"Alert {reference}",
            created_at=(
                now - timedelta(seconds=1) if status == AlertStatus.CLOSED else now
            ),
            closed_at=now if status == AlertStatus.CLOSED else None,
        )
        db.session.add(alert)
        db.session.flush()
        return alert

    open_alert = make_alert("ALT-CASE-OPEN")
    acknowledged_alert = make_alert(
        "ALT-CASE-ACK",
        AlertStatus.ACKNOWLEDGED,
    )
    closed_alert = make_alert("ALT-CASE-CLOSED", AlertStatus.CLOSED)
    db.session.commit()
    return {
        "analyst": analyst,
        "other_analyst": other_analyst,
        "supervisor": supervisor,
        "admin": admin,
        "open_alert": open_alert,
        "acknowledged_alert": acknowledged_alert,
        "closed_alert": closed_alert,
    }


def _create_case(actor: User, alert_ids: list[int]) -> Case:
    return create_case(
        db.session,
        actor,
        title="Suspicious activity review",
        description="Investigate linked transaction alerts.",
        priority=CasePriority.HIGH,
        alert_ids=alert_ids,
    )


def _login(client, user_id: int) -> None:
    with client.session_transaction() as browser_session:
        browser_session["_user_id"] = str(user_id)
        browser_session["_fresh"] = True


def test_case_creation_links_alerts_assigns_creator_and_audits(cases_app):
    with cases_app.app_context():
        data = _seed_case_data()
        alert = data["open_alert"]
        original_alert = (alert.status, alert.score, alert.summary)
        case = _create_case(data["analyst"], [alert.id])
        db.session.commit()

        assert case.assigned_to_user_id == data["analyst"].id
        assert case.opened_by_user_id == data["analyst"].id
        assert case.status is CaseStatus.OPEN
        link = db.session.scalar(
            select(CaseAlert).where(
                CaseAlert.case_id == case.id,
                CaseAlert.alert_id == alert.id,
                CaseAlert.unlinked_at.is_(None),
            )
        )
        assert link is not None
        assert link.linked_by_user_id == data["analyst"].id
        assert get_active_case_for_alert(db.session, alert.id) == {
            "id": case.id,
            "reference": case.case_reference,
        }
        event = db.session.scalar(
            select(AuditEvent).where(
                AuditEvent.entity_type == "case",
                AuditEvent.entity_id == case.id,
                AuditEvent.event_type == "CASE_CREATED",
            )
        )
        assert event is not None
        assert event.actor_user_id == data["analyst"].id
        assert (alert.status, alert.score, alert.summary) == original_alert


def test_case_creation_rejects_missing_duplicate_or_ineligible_alerts(cases_app):
    with cases_app.app_context():
        data = _seed_case_data()
        with pytest.raises(ValidationError, match="Select between"):
            _create_case(data["analyst"], [])
        with pytest.raises(ValidationError, match="selected only once"):
            _create_case(
                data["analyst"],
                [data["open_alert"].id, data["open_alert"].id],
            )
        with pytest.raises(ValidationError, match="Only open or acknowledged"):
            _create_case(data["analyst"], [data["closed_alert"].id])
        assert db.session.scalar(select(func.count(Case.id))) == 0


def test_alert_cannot_have_two_active_case_links_and_unlink_is_soft(cases_app):
    with cases_app.app_context():
        data = _seed_case_data()
        case = _create_case(data["analyst"], [data["open_alert"].id])
        db.session.flush()
        with pytest.raises(ValidationError, match="already linked"):
            link_alert_to_case(
                db.session,
                case.id,
                data["open_alert"].id,
                data["analyst"],
            )
        link = db.session.scalar(select(CaseAlert).where(CaseAlert.case_id == case.id))
        with pytest.raises(ValidationError, match="retain at least one"):
            unlink_alert_from_case(
                db.session,
                case.id,
                link.id,
                data["analyst"],
                "Remove this alert",
            )
        link_two = link_alert_to_case(
            db.session,
            case.id,
            data["acknowledged_alert"].id,
            data["analyst"],
        )
        db.session.flush()
        unlink_alert_from_case(
            db.session,
            case.id,
            link.id,
            data["analyst"],
            "Duplicate investigation entry",
        )
        db.session.commit()

        stored_link = db.session.get(CaseAlert, link.id)
        assert stored_link is not None
        assert stored_link.unlinked_at is not None
        assert stored_link.unlinked_by_user_id == data["analyst"].id
        assert stored_link.unlink_reason == "Duplicate investigation entry"
        assert link_two.unlinked_at is None
        assert get_active_case_for_alert(db.session, data["open_alert"].id) is None


def test_only_open_or_acknowledged_alerts_can_be_linked(cases_app):
    with cases_app.app_context():
        data = _seed_case_data()
        case = _create_case(data["analyst"], [data["open_alert"].id])
        with pytest.raises(ValidationError, match="Only open or acknowledged"):
            link_alert_to_case(
                db.session,
                case.id,
                data["closed_alert"].id,
                data["analyst"],
            )
        assert len(list_eligible_alerts(db.session)) == 1
        assert (
            list_eligible_alerts(db.session)[0]["id"] == data["acknowledged_alert"].id
        )


def test_case_status_transitions_and_required_reasons(cases_app):
    with cases_app.app_context():
        data = _seed_case_data()
        case = _create_case(data["analyst"], [data["open_alert"].id])
        db.session.flush()

        with pytest.raises(ValidationError, match="reason is required"):
            transition_case(
                db.session,
                case.id,
                data["supervisor"],
                CaseStatus.ESCALATED,
            )
        transition_case(
            db.session,
            case.id,
            data["analyst"],
            CaseStatus.IN_REVIEW,
        )
        transition_case(
            db.session,
            case.id,
            data["analyst"],
            CaseStatus.OPEN,
        )
        with pytest.raises(ValidationError, match="Only supervisors and admins"):
            transition_case(
                db.session,
                case.id,
                data["analyst"],
                CaseStatus.ESCALATED,
                "Requires supervisor review",
            )
        transition_case(
            db.session,
            case.id,
            data["supervisor"],
            CaseStatus.ESCALATED,
            "Requires supervisor review",
        )
        transition_case(
            db.session,
            case.id,
            data["supervisor"],
            CaseStatus.IN_REVIEW,
        )
        with pytest.raises(ValidationError, match="Only supervisors and admins"):
            transition_case(
                db.session,
                case.id,
                data["analyst"],
                CaseStatus.CLOSED,
                "Resolved",
            )
        transition_case(
            db.session,
            case.id,
            data["supervisor"],
            CaseStatus.CLOSED,
            "Investigation complete",
        )
        assert case.status is CaseStatus.CLOSED
        assert case.closed_at is not None
        assert case.closed_by_user_id == data["supervisor"].id
        with pytest.raises(ValidationError, match="closed case cannot be changed"):
            transition_case(
                db.session,
                case.id,
                data["supervisor"],
                CaseStatus.OPEN,
            )
        events = list(
            db.session.scalars(
                select(AuditEvent).where(
                    AuditEvent.entity_type == "case",
                    AuditEvent.entity_id == case.id,
                )
            ).all()
        )
        assert [event.event_type for event in events].count(
            "CASE_STATUS_ESCALATED"
        ) == 1
        assert [event.event_type for event in events].count("CASE_STATUS_CLOSED") == 1


def test_case_status_matrix_rejects_invalid_edges(cases_app):
    with cases_app.app_context():
        data = _seed_case_data()
        case = _create_case(data["analyst"], [data["open_alert"].id])
        db.session.flush()
        with pytest.raises(ValidationError, match="Cannot move a OPEN case to OPEN"):
            transition_case(
                db.session,
                case.id,
                data["supervisor"],
                CaseStatus.OPEN,
            )

        transition_case(
            db.session,
            case.id,
            data["analyst"],
            CaseStatus.IN_REVIEW,
        )
        transition_case(
            db.session,
            case.id,
            data["supervisor"],
            CaseStatus.ESCALATED,
            "Escalation reason",
        )
        with pytest.raises(
            ValidationError, match="Cannot move a ESCALATED case to OPEN"
        ):
            transition_case(
                db.session,
                case.id,
                data["supervisor"],
                CaseStatus.OPEN,
            )


def test_analyst_ownership_claim_and_manager_oversight(cases_app):
    with cases_app.app_context():
        data = _seed_case_data()
        owned_case = _create_case(data["analyst"], [data["open_alert"].id])
        db.session.flush()
        with pytest.raises(ValidationError, match="assigned to you"):
            add_case_note(
                db.session,
                owned_case.id,
                data["other_analyst"],
                body="Not authorized",
            )
        with pytest.raises(ValidationError, match="Only supervisors and admins"):
            set_case_priority(
                db.session,
                owned_case.id,
                data["analyst"],
                CasePriority.CRITICAL,
            )
        set_case_priority(
            db.session,
            owned_case.id,
            data["supervisor"],
            CasePriority.CRITICAL,
        )
        assign_case(
            db.session,
            owned_case.id,
            data["supervisor"],
            data["other_analyst"].id,
        )
        assert owned_case.assigned_to_user_id == data["other_analyst"].id

        unassigned = _create_case(data["analyst"], [data["acknowledged_alert"].id])
        db.session.flush()
        unassigned.assigned_to_user_id = None
        db.session.flush()
        claim_case(db.session, unassigned.id, data["other_analyst"])
        assert unassigned.assigned_to_user_id == data["other_analyst"].id
        with pytest.raises(ValidationError, match="Only an unassigned case"):
            claim_case(db.session, unassigned.id, data["analyst"])
        with pytest.raises(ValidationError, match="Only supervisors and admins"):
            assign_case(
                db.session,
                unassigned.id,
                data["analyst"],
                data["analyst"].id,
            )


def test_notes_decisions_and_audit_are_append_only(cases_app):
    with cases_app.app_context():
        data = _seed_case_data()
        case = _create_case(
            data["analyst"],
            [data["open_alert"].id, data["acknowledged_alert"].id],
        )
        db.session.flush()
        note = add_case_note(
            db.session,
            case.id,
            data["analyst"],
            body="Reviewed transaction evidence.",
            note_type=CaseNoteType.INVESTIGATION,
        )
        decision = add_case_decision(
            db.session,
            case.id,
            data["analyst"],
            alert_id=data["open_alert"].id,
            decision=CaseDecisionType.MONITOR,
            rationale="Continue monitoring the account.",
        )
        db.session.commit()

        detail = get_case_detail(db.session, case.id)
        assert detail is not None
        assert detail["notes"][0]["body"] == "Reviewed transaction evidence."
        assert detail["decisions"][0]["alert_reference"] == "ALT-CASE-OPEN"
        assert {event["event_type"] for event in detail["audit_events"]} >= {
            "CASE_CREATED",
            "CASE_NOTE_ADDED",
            "CASE_DECISION_RECORDED",
        }
        assert note is not None
        assert decision is not None
        note.body = "Changed"
        with pytest.raises(AppendOnlyError):
            db.session.flush()
        db.session.rollback()

        decision_record = db.session.get(CaseDecision, decision.id)
        assert decision_record is not None
        decision_record.rationale = "Changed"
        with pytest.raises(AppendOnlyError):
            db.session.flush()
        db.session.rollback()


def test_decision_requires_active_case_alert_and_rationale(cases_app):
    with cases_app.app_context():
        data = _seed_case_data()
        case = _create_case(data["analyst"], [data["open_alert"].id])
        db.session.flush()
        with pytest.raises(ValidationError, match="rationale"):
            add_case_decision(
                db.session,
                case.id,
                data["analyst"],
                alert_id=data["open_alert"].id,
                decision=CaseDecisionType.MONITOR,
                rationale=" ",
            )
        with pytest.raises(ValidationError, match="actively linked"):
            add_case_decision(
                db.session,
                case.id,
                data["analyst"],
                alert_id=data["acknowledged_alert"].id,
                decision=CaseDecisionType.MONITOR,
                rationale="Not linked",
            )


def test_case_queue_has_stable_pagination_and_filters(cases_app):
    with cases_app.app_context():
        data = _seed_case_data()
        cases = []
        for index in range(23):
            case = Case(
                case_reference=f"CASE-QUEUE-{index:02d}",
                title=f"Queue case {index:02d}",
                status=CaseStatus.OPEN,
                priority=CasePriority.HIGH if index % 2 else CasePriority.LOW,
                opened_by_user_id=data["analyst"].id,
                assigned_to_user_id=(data["analyst"].id if index % 2 else None),
                opened_at=utc_now() + timedelta(seconds=index),
            )
            db.session.add(case)
            cases.append(case)
        db.session.commit()

        first = list_cases(db.session, page=1, per_page=10)
        second = list_cases(db.session, page=2, per_page=10)
        filtered = list_cases(
            db.session,
            status=CaseStatus.OPEN,
            priority=CasePriority.HIGH,
            assigned_to_user_id=data["analyst"].id,
            q="queue case",
        )
        unassigned = list_cases(db.session, unassigned_only=True)
        visible_to_analyst = list_cases(
            db.session,
            visible_to_user_id=data["analyst"].id,
        )

        assert first["pagination"]["total"] == 23
        assert len(first["items"]) == 10
        assert len(second["items"]) == 10
        assert first["items"][0]["id"] != first["items"][1]["id"]
        assert {item["id"] for item in first["items"]}.isdisjoint(
            item["id"] for item in second["items"]
        )
        assert filtered["pagination"]["total"] == 11
        assert all(item["priority"] == "HIGH" for item in filtered["items"])
        assert unassigned["pagination"]["total"] == 12
        assert visible_to_analyst["pagination"]["total"] == 23


def test_analyst_queue_and_detail_hide_other_reviewers_cases(cases_app):
    with cases_app.app_context():
        data = _seed_case_data()
        assigned_to_other = _create_case(data["analyst"], [data["open_alert"].id])
        assigned_to_other.assigned_to_user_id = data["other_analyst"].id
        unassigned = _create_case(data["analyst"], [data["acknowledged_alert"].id])
        unassigned.assigned_to_user_id = None
        db.session.commit()
        other_case_id = assigned_to_other.id
        unassigned_case_id = unassigned.id
        analyst_id = data["analyst"].id
        other_reference = assigned_to_other.case_reference
        unassigned_reference = unassigned.case_reference

    client = cases_app.test_client()
    _login(client, analyst_id)
    queue = client.get("/cases/")
    assert queue.status_code == 200
    assert unassigned_reference.encode() in queue.data
    assert other_reference.encode() not in queue.data
    assert client.get(f"/cases/{other_case_id}").status_code == 404
    unassigned_page = client.get(f"/cases/{unassigned_case_id}")
    assert unassigned_page.status_code == 200
    assert b"Claim this case" in unassigned_page.data


def test_case_routes_create_link_list_and_return_404(cases_app):
    with cases_app.app_context():
        data = _seed_case_data()
        user_id = data["analyst"].id
        alert_id = data["open_alert"].id

    unauthenticated_client = cases_app.test_client()
    response = unauthenticated_client.get("/cases/")
    assert response.status_code == 302
    client = cases_app.test_client()
    _login(client, user_id)
    alert_page = client.get(f"/alerts/{alert_id}")
    assert b"Create case with this alert" in alert_page.data
    create_page = client.get(f"/cases/new?alert_id={alert_id}")
    assert b"Eligible alerts" in create_page.data
    response = client.post(
        "/cases/new",
        data={
            "title": "Route-created investigation",
            "description": "Case created through the analyst workflow.",
            "priority": "HIGH",
            "alert_ids": str(alert_id),
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Route-created investigation" in response.data
    assert b"Case created" in response.data
    with cases_app.app_context():
        assert get_active_case_for_alert(db.session, alert_id) is not None
    assert client.get("/cases/99999").status_code == 404


def test_case_mutation_commit_failure_rolls_back(cases_app, monkeypatch):
    with cases_app.app_context():
        data = _seed_case_data()
        case = _create_case(data["analyst"], [data["open_alert"].id])
        db.session.commit()
        case_id = case.id
        session = db.session
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
        with pytest.raises(SQLAlchemyError, match="simulated commit failure"):
            _execute_case_action(
                case_id,
                lambda: transition_case(
                    session,
                    case_id,
                    data["analyst"],
                    CaseStatus.IN_REVIEW,
                ),
                "Case status updated.",
            )
        assert rollback_calls == 1
        monkeypatch.undo()
        stored_case = db.session.get(Case, case_id)
        assert stored_case is not None
        assert stored_case.status is CaseStatus.OPEN
        assert (
            db.session.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.entity_type == "case",
                    AuditEvent.entity_id == case_id,
                    AuditEvent.event_type == "CASE_STATUS_IN_REVIEW",
                )
            )
            == 0
        )
