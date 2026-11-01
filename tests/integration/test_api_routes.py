"""Route integration tests for the authenticated versioned operations API."""

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app import create_app
from app.extensions import db
from app.models import (
    Account,
    Alert,
    AuditEvent,
    Base,
    Case,
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
    CaseStatus,
    CurrencyCode,
    RiskLevel,
    RiskSeverity,
    TransactionStatus,
    TransactionType,
    UserRole,
)
from app.services.cases import get_case_detail


@pytest.fixture()
def api_app():
    test_app = create_app("testing")
    with test_app.app_context():
        Base.metadata.create_all(db.engine)
    yield test_app
    with test_app.app_context():
        db.session.remove()
        Base.metadata.drop_all(db.engine)


@pytest.fixture()
def api_client(api_app):
    return api_app.test_client()


def _create_user(suffix: str, role: UserRole = UserRole.ANALYST) -> User:
    user = User(
        username=f"api_{suffix}",
        email=f"api_{suffix}@yottaflex.test",
        full_name=f"API Reviewer {suffix}",
        role=role,
        is_active=True,
    )
    user.set_password("SecurePassword123!")
    db.session.add(user)
    db.session.flush()
    return user


def _seed_api_records(api_app) -> dict[str, int]:
    with api_app.app_context():
        now = utc_now()
        analyst = _create_user("analyst")
        other_analyst = _create_user("other")
        supervisor = _create_user("supervisor", UserRole.SUPERVISOR)
        admin = _create_user("admin", UserRole.ADMIN)
        customer = Customer(
            customer_reference="CUST-API-1",
            first_name="API",
            last_name="Customer",
            email="private@example.test",
            phone="555-0101",
            country_code="US",
            onboarding_date=now.date(),
        )
        db.session.add(customer)
        db.session.flush()
        account = Account(
            account_number="ACC-API-1",
            customer_id=customer.id,
            account_type=AccountType.CHECKING,
            currency=CurrencyCode.USD,
            status=AccountStatus.ACTIVE,
            balance=Decimal("1000.00"),
            overdraft_limit=Decimal("0.00"),
            opened_at=now - timedelta(days=30),
        )
        db.session.add(account)
        rule = RiskRule(
            code="API_TEST_RULE",
            version=1,
            name="API test rule",
            category="TEST",
            severity=RiskSeverity.HIGH,
            score_weight=50,
            configuration={},
            is_active=True,
            effective_from=now - timedelta(days=1),
        )
        db.session.add(rule)
        alternate_rule = RiskRule(
            code="API_TEST_RULE_ALT",
            version=1,
            name="Alternate API test rule",
            category="TEST",
            severity=RiskSeverity.HIGH,
            score_weight=45,
            configuration={},
            is_active=True,
            effective_from=now - timedelta(days=1),
        )
        db.session.add(alternate_rule)
        db.session.flush()
        transaction = Transaction(
            transaction_reference="TX-API-1",
            debit_account_id=account.id,
            transaction_type=TransactionType.OUTGOING,
            status=TransactionStatus.POSTED,
            amount=Decimal("500.00"),
            currency=CurrencyCode.USD,
            occurred_at=now,
            debit_account_status_snapshot=AccountStatus.ACTIVE,
        )
        db.session.add(transaction)
        db.session.flush()
        assessment = RiskAssessment(
            transaction_id=transaction.id,
            model_version="api-test-v1",
            score=70,
            risk_level=RiskLevel.HIGH,
            status=AssessmentStatus.COMPLETED,
            assessed_at=now,
            explanation={"summary": "Stored API assessment."},
        )
        db.session.add(assessment)
        db.session.flush()

        def make_alert(
            reference: str,
            status: AlertStatus,
            alert_rule: RiskRule,
        ) -> Alert:
            finding = RiskFinding(
                assessment_id=assessment.id,
                rule_id=alert_rule.id,
                rule_code=alert_rule.code,
                score=50,
                severity=RiskSeverity.HIGH,
                explanation="Stored API finding.",
                evidence={
                    "amount": "500.00",
                    "threshold": "100.00",
                    "customer_email": "private@example.test",
                    "device_fingerprint": "private-device",
                },
            )
            db.session.add(finding)
            db.session.flush()
            alert = Alert(
                alert_reference=reference,
                transaction_id=transaction.id,
                assessment_id=assessment.id,
                finding_id=finding.id,
                triggering_rule_id=alert_rule.id,
                status=status,
                priority=AlertPriority.HIGH,
                score=70,
                summary=f"Alert {reference}",
                details={
                    "triggering_rule_code": alert_rule.code,
                    "findings_count": 1,
                    "effective_threshold": 40,
                    "evidence": finding.evidence,
                },
                created_at=now,
            )
            db.session.add(alert)
            db.session.flush()
            return alert

        open_alert = make_alert("ALT-API-OPEN", AlertStatus.OPEN, rule)
        acknowledged_alert = make_alert(
            "ALT-API-ACK",
            AlertStatus.ACKNOWLEDGED,
            alternate_rule,
        )
        db.session.commit()
        return {
            "analyst_id": analyst.id,
            "other_analyst_id": other_analyst.id,
            "supervisor_id": supervisor.id,
            "admin_id": admin.id,
            "account_id": account.id,
            "transaction_id": transaction.id,
            "open_alert_id": open_alert.id,
            "acknowledged_alert_id": acknowledged_alert.id,
        }


def _login(client, user_id: int) -> None:
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_api_requires_session_auth_and_validates_queries(api_client, api_app):
    response = api_client.get("/api/v1/cases")
    assert response.status_code == 401
    assert response.json["error"]["code"] == "unauthorized"

    ids = _seed_api_records(api_app)
    _login(api_client, ids["analyst_id"])
    assert api_client.get("/api/v1/cases?unexpected=1").status_code == 422
    assert api_client.get("/api/v1/cases?page=1&page=2").status_code == 422
    assert api_client.get("/api/v1/alerts?per_page=101").status_code == 422
    assert api_client.get("/api/v1/transactions").status_code == 422


def test_alert_reads_use_pii_allowlist(api_client, api_app):
    ids = _seed_api_records(api_app)
    _login(api_client, ids["analyst_id"])

    response = api_client.get("/api/v1/alerts")
    assert response.status_code == 200
    assert response.json["pagination"]["total"] == 2
    detail = api_client.get(f"/api/v1/alerts/{ids['open_alert_id']}")
    assert detail.status_code == 200
    payload = detail.get_data(as_text=True)
    assert "private@example.test" not in payload
    assert "555-0101" not in payload
    assert "balance" not in payload
    assert "device_fingerprint" not in payload
    assert "customer_email" not in payload

    missing = api_client.get("/api/v1/alerts/999999")
    assert missing.status_code == 404


def test_alert_mutations_require_csrf_and_record_audit(api_client, api_app):
    ids = _seed_api_records(api_app)
    api_app.config["WTF_CSRF_ENABLED"] = True
    _login(api_client, ids["analyst_id"])

    path = f"/api/v1/alerts/{ids['open_alert_id']}/acknowledge"
    rejected = api_client.post(path, json={})
    assert rejected.status_code == 400
    assert rejected.json["error"]["code"] == "csrf_failed"

    token_response = api_client.get("/api/v1/csrf-token")
    assert token_response.status_code == 200
    assert token_response.headers["Cache-Control"] == "no-store"
    token = token_response.json["data"]["csrf_token"]
    acknowledged = api_client.post(
        path,
        json={},
        headers={"X-CSRFToken": token},
    )
    assert acknowledged.status_code == 200
    assert acknowledged.json["data"]["status"] == "ACKNOWLEDGED"

    close_response = api_client.post(
        f"/api/v1/alerts/{ids['open_alert_id']}/close",
        json={"reason": "Reviewed"},
        headers={"X-CSRFToken": token},
    )
    assert close_response.status_code == 200
    with api_app.app_context():
        events = db.session.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.entity_type == "alert",
                AuditEvent.entity_id == ids["open_alert_id"],
            )
        )
        alert = db.session.get(Alert, ids["open_alert_id"])
        assert events == 2
        assert alert.status == AlertStatus.CLOSED


def test_alert_assignment_and_dismissal_use_existing_workflows(api_client, api_app):
    ids = _seed_api_records(api_app)
    _login(api_client, ids["analyst_id"])

    assigned = api_client.post(
        f"/api/v1/alerts/{ids['open_alert_id']}/assignment",
        json={"assignee_id": ids["other_analyst_id"]},
    )
    assert assigned.status_code == 200
    assert assigned.json["data"]["assigned_to_user_id"] == ids["other_analyst_id"]

    dismissed = api_client.post(
        f"/api/v1/alerts/{ids['acknowledged_alert_id']}/dismiss",
        json={"reason": "Not actionable"},
    )
    assert dismissed.status_code == 200
    assert dismissed.json["data"]["status"] == "DISMISSED"

    with api_app.app_context():
        assert (
            db.session.get(Alert, ids["open_alert_id"]).assigned_to_user_id
            == ids["other_analyst_id"]
        )
        assert (
            db.session.get(Alert, ids["acknowledged_alert_id"]).status
            is AlertStatus.DISMISSED
        )


def test_transaction_lookup_and_account_history_are_read_only(api_client, api_app):
    ids = _seed_api_records(api_app)
    _login(api_client, ids["analyst_id"])

    lookup = api_client.get("/api/v1/transactions?q=TX-API-1")
    assert lookup.status_code == 200
    assert lookup.json["data"]["transaction"]["id"] == ids["transaction_id"]
    assert lookup.json["data"]["transfer_legs_pagination"]["limit"] == 100
    assert "private@example.test" not in lookup.get_data(as_text=True)
    assert "customer_email" not in lookup.get_data(as_text=True)
    assert "device_fingerprint" not in lookup.get_data(as_text=True)

    history = api_client.get(
        f"/api/v1/accounts/{ids['account_id']}/transactions?per_page=1"
    )
    assert history.status_code == 200
    assert history.json["pagination"]["total"] == 1
    assert history.json["data"]["items"][0]["reference"] == "TX-API-1"

    with api_app.app_context():
        assert db.session.get(Alert, ids["open_alert_id"]).status == AlertStatus.OPEN
        assert db.session.get(Transaction, ids["transaction_id"]).amount == Decimal(
            "500.00"
        )
        assert db.session.scalar(select(func.count(AuditEvent.id))) == 0


def test_case_create_visibility_and_audit(api_client, api_app):
    ids = _seed_api_records(api_app)
    _login(api_client, ids["analyst_id"])

    created = api_client.post(
        "/api/v1/cases",
        json={
            "title": "Investigate transaction",
            "description": "Review stored alert evidence.",
            "alert_ids": [ids["open_alert_id"]],
        },
    )
    assert created.status_code == 201
    case_id = created.json["data"]["id"]
    assert created.json["data"]["status"] == "OPEN"

    detail = api_client.get(f"/api/v1/cases/{case_id}")
    assert detail.status_code == 200
    assert len(detail.json["data"]["links"]) == 1
    assert detail.json["data"]["audit_events"][0]["event_type"] == "CASE_CREATED"

    missing_detail = api_client.get("/api/v1/cases/999999")
    assert missing_detail.status_code == 404

    _login(api_client, ids["other_analyst_id"])
    unauthorized_detail = api_client.get(f"/api/v1/cases/{case_id}")
    assert unauthorized_detail.status_code == 404
    assert unauthorized_detail.json == missing_detail.json

    hidden_claim = api_client.post(f"/api/v1/cases/{case_id}/claim", json={})
    missing_claim = api_client.post("/api/v1/cases/999999/claim", json={})
    assert hidden_claim.status_code == missing_claim.status_code == 404
    assert (
        hidden_claim.json
        == missing_claim.json
        == {
            "error": {
                "code": "not_found",
                "message": "The requested resource was not found.",
            }
        }
    )

    hidden_note = api_client.post(
        f"/api/v1/cases/{case_id}/notes",
        json={"body": "Should not be accepted"},
    )
    missing_note = api_client.post(
        "/api/v1/cases/999999/notes",
        json={"body": "Should not be accepted"},
    )
    assert hidden_note.status_code == missing_note.status_code == 404
    assert hidden_note.json == missing_note.json
    assert api_client.get("/api/v1/cases").status_code == 200

    _login(api_client, ids["analyst_id"])
    authorized_detail = api_client.get(f"/api/v1/cases/{case_id}")
    authorized_note = api_client.post(
        f"/api/v1/cases/{case_id}/notes",
        json={"body": "Authorized investigation note"},
    )
    assert authorized_detail.status_code == 200
    assert authorized_note.status_code == 201

    with api_app.app_context():
        case_events = db.session.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.entity_type == "case",
                AuditEvent.entity_id == case_id,
            )
        )
        assert case_events == 2


def test_case_links_notes_and_decisions_preserve_history(api_client, api_app):
    ids = _seed_api_records(api_app)
    _login(api_client, ids["analyst_id"])
    created = api_client.post(
        "/api/v1/cases",
        json={
            "title": "Review linked alerts",
            "alert_ids": [ids["open_alert_id"], ids["acknowledged_alert_id"]],
        },
    )
    assert created.status_code == 201
    case_id = created.json["data"]["id"]
    detail = api_client.get(f"/api/v1/cases/{case_id}").json["data"]
    first_link_id = detail["links"][0]["id"]
    first_alert_id = detail["links"][0]["alert_id"]

    duplicate = api_client.post(
        f"/api/v1/cases/{case_id}/alerts",
        json={"alert_id": first_alert_id},
    )
    assert duplicate.status_code == 409

    note = api_client.post(
        f"/api/v1/cases/{case_id}/notes",
        json={"body": "Evidence reviewed", "note_type": "INVESTIGATION"},
    )
    assert note.status_code == 201
    decision = api_client.post(
        f"/api/v1/cases/{case_id}/decisions",
        json={
            "alert_id": first_alert_id,
            "decision": "MONITOR",
            "rationale": "Continue monitoring linked activity.",
        },
    )
    assert decision.status_code == 201

    unlink = api_client.post(
        f"/api/v1/cases/{case_id}/alerts/{first_link_id}/unlink",
        json={"reason": "Consolidated review"},
    )
    assert unlink.status_code == 200
    final_detail = api_client.get(f"/api/v1/cases/{case_id}").json["data"]
    link_history = next(
        link for link in final_detail["links"] if link["id"] == first_link_id
    )
    assert link_history["active"] is False
    assert link_history["unlink_reason"] == "Consolidated review"
    assert len(final_detail["notes"]) == 1
    assert len(final_detail["decisions"]) == 1
    relinked = api_client.post(
        f"/api/v1/cases/{case_id}/alerts",
        json={"alert_id": first_alert_id},
    )
    assert relinked.status_code == 201
    final_detail = api_client.get(f"/api/v1/cases/{case_id}").json["data"]
    assert sum(link["active"] for link in final_detail["links"]) == 2
    assert {event["event_type"] for event in final_detail["audit_events"]} >= {
        "CASE_NOTE_ADDED",
        "CASE_DECISION_RECORDED",
        "CASE_ALERT_UNLINKED",
    }


def test_case_manager_permissions_and_terminal_status(api_client, api_app):
    ids = _seed_api_records(api_app)
    _login(api_client, ids["analyst_id"])
    created = api_client.post(
        "/api/v1/cases",
        json={
            "title": "Manager oversight",
            "alert_ids": [ids["open_alert_id"]],
        },
    )
    case_id = created.json["data"]["id"]

    forbidden = api_client.post(
        f"/api/v1/cases/{case_id}/priority",
        json={"priority": "CRITICAL"},
    )
    assert forbidden.status_code == 404

    _login(api_client, ids["supervisor_id"])
    missing_reason = api_client.post(
        f"/api/v1/cases/{case_id}/status",
        json={"status": "CLOSED"},
    )
    assert missing_reason.status_code == 422
    closed = api_client.post(
        f"/api/v1/cases/{case_id}/status",
        json={"status": "CLOSED", "reason": "Review complete"},
    )
    assert closed.status_code == 200
    assert closed.json["data"]["status"] == "CLOSED"
    terminal = api_client.post(
        f"/api/v1/cases/{case_id}/status",
        json={"status": "OPEN"},
    )
    assert terminal.status_code == 409

    with api_app.app_context():
        detail = get_case_detail(db.session, case_id)
        assert detail["case"]["status"] == CaseStatus.CLOSED.value
        assert any(
            event["event_type"] == "CASE_STATUS_CLOSED"
            for event in detail["audit_events"]
        )


def test_claim_hides_closed_case_from_unauthorized_analyst(api_client, api_app):
    ids = _seed_api_records(api_app)
    _login(api_client, ids["analyst_id"])
    created = api_client.post(
        "/api/v1/cases",
        json={
            "title": "Closed case visibility",
            "alert_ids": [ids["open_alert_id"]],
        },
    )
    assert created.status_code == 201
    case_id = created.json["data"]["id"]

    _login(api_client, ids["supervisor_id"])
    closed = api_client.post(
        f"/api/v1/cases/{case_id}/status",
        json={"status": "CLOSED", "reason": "Review complete"},
    )
    assert closed.status_code == 200
    assert closed.json["data"]["status"] == "CLOSED"

    _login(api_client, ids["other_analyst_id"])
    hidden_claim = api_client.post(f"/api/v1/cases/{case_id}/claim", json={})
    missing_claim = api_client.post("/api/v1/cases/999999/claim", json={})
    assert hidden_claim.status_code == missing_claim.status_code == 404
    assert hidden_claim.json == missing_claim.json

    _login(api_client, ids["analyst_id"])
    authorized_detail = api_client.get(f"/api/v1/cases/{case_id}")
    authorized_claim = api_client.post(f"/api/v1/cases/{case_id}/claim", json={})
    assert authorized_detail.status_code == 200
    assert authorized_detail.json["data"]["case"]["status"] == "CLOSED"
    assert authorized_claim.status_code == 409
    assert authorized_claim.json["error"]["code"] == "case_closed"


def test_case_assignment_is_manager_only_and_claim_is_analyst_only(api_client, api_app):
    ids = _seed_api_records(api_app)
    _login(api_client, ids["analyst_id"])
    created = api_client.post(
        "/api/v1/cases",
        json={
            "title": "Assignment workflow",
            "alert_ids": [ids["open_alert_id"]],
        },
    )
    case_id = created.json["data"]["id"]
    _login(api_client, ids["other_analyst_id"])
    analyst_assignment = api_client.post(
        f"/api/v1/cases/{case_id}/assignment",
        json={"assignee_id": ids["other_analyst_id"]},
    )
    missing_assignment = api_client.post(
        "/api/v1/cases/999999/assignment",
        json={"assignee_id": ids["other_analyst_id"]},
    )
    assert analyst_assignment.status_code == missing_assignment.status_code == 404
    assert analyst_assignment.json == missing_assignment.json

    analyst_priority = api_client.post(
        f"/api/v1/cases/{case_id}/priority",
        json={"priority": "CRITICAL"},
    )
    missing_priority = api_client.post(
        "/api/v1/cases/999999/priority",
        json={"priority": "CRITICAL"},
    )
    assert analyst_priority.status_code == missing_priority.status_code == 404
    assert analyst_priority.json == missing_priority.json

    _login(api_client, ids["supervisor_id"])
    priority = api_client.post(
        f"/api/v1/cases/{case_id}/priority",
        json={"priority": "HIGH"},
    )
    assert priority.status_code == 200
    assert priority.json["data"]["priority"] == "HIGH"
    assigned = api_client.post(
        f"/api/v1/cases/{case_id}/assignment",
        json={"assignee_id": ids["other_analyst_id"]},
    )
    assert assigned.status_code == 200
    assert assigned.json["data"]["assigned_to_user_id"] == ids["other_analyst_id"]

    _login(api_client, ids["admin_id"])
    claimed = api_client.post(f"/api/v1/cases/{case_id}/claim", json={})
    assert claimed.status_code == 403
    unassigned = api_client.post(
        f"/api/v1/cases/{case_id}/assignment",
        json={"assignee_id": None},
    )
    assert unassigned.status_code == 200

    _login(api_client, ids["analyst_id"])
    claimed = api_client.post(f"/api/v1/cases/{case_id}/claim", json={})
    assert claimed.status_code == 200
    assert claimed.json["data"]["assigned_to_user_id"] == ids["analyst_id"]


def test_case_api_commit_failure_rolls_back_case_and_audit(
    api_client, api_app, monkeypatch
):
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.orm import Session

    ids = _seed_api_records(api_app)
    _login(api_client, ids["analyst_id"])

    def fail_commit(_session):
        del _session
        raise SQLAlchemyError("simulated API commit failure")

    monkeypatch.setattr(Session, "commit", fail_commit)
    with pytest.raises(SQLAlchemyError, match="simulated API commit failure"):
        api_client.post(
            "/api/v1/cases",
            json={
                "title": "Must roll back",
                "alert_ids": [ids["open_alert_id"]],
            },
        )

    monkeypatch.undo()
    with api_app.app_context():
        assert db.session.scalar(select(func.count(Case.id))) == 0
        assert (
            db.session.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.entity_type == "case"
                )
            )
            == 0
        )


def test_api_rejects_bad_json_body_and_hides_missing_resources(api_client, api_app):
    ids = _seed_api_records(api_app)
    _login(api_client, ids["analyst_id"])

    malformed = api_client.post(
        "/api/v1/cases",
        data="{not json",
        content_type="application/json",
    )
    assert malformed.status_code == 400

    missing_tx = api_client.get("/api/v1/transactions/999999")
    missing_account = api_client.get("/api/v1/accounts/999999/transactions")
    missing_case = api_client.get("/api/v1/cases/999999")
    assert missing_tx.status_code == 404
    assert missing_account.status_code == 404
    assert missing_case.status_code == 404
