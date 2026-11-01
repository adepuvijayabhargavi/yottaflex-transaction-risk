"""Dashboard KPIs, metrics aggregation, API, and ground-truth isolation tests."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app import create_app
from app.extensions import db
from app.models import (
    Account,
    Alert,
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
    CasePriority,
    CaseStatus,
    CurrencyCode,
    CustomerRiskSegment,
    RiskLevel,
    RiskSeverity,
    TransactionStatus,
    TransactionType,
    UserRole,
)
from app.services.dashboard import get_dashboard_stats


@pytest.fixture()
def dashboard_app():
    """Create a Flask test application with initialized database tables."""
    test_app = create_app("testing")
    with test_app.app_context():
        Base.metadata.create_all(db.engine)
        yield test_app
        db.session.rollback()
        Base.metadata.drop_all(db.engine)


@pytest.fixture()
def dashboard_client(dashboard_app):
    """Test client for dashboard tests."""
    return dashboard_app.test_client()


def _setup_analyst_user(username: str = "analyst_dash") -> User:
    user = User(
        username=username,
        email=f"{username}@yottaflex.bank",
        full_name="Dashboard Analyst",
        role=UserRole.ANALYST,
        is_active=True,
    )
    user.set_password("SecurePassword123!")
    db.session.add(user)
    db.session.commit()
    return user


def test_dashboard_unauthenticated_redirect(dashboard_client):
    """GET /dashboard unauthenticated redirects to /login."""
    response = dashboard_client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_dashboard_api_unauthenticated_401(dashboard_client):
    """GET /api/v1/dashboard/stats unauthenticated returns 401 JSON."""
    response = dashboard_client.get("/api/v1/dashboard/stats")
    assert response.status_code == 401
    assert response.is_json
    assert response.get_json()["error"] == "unauthorized"


def test_get_dashboard_stats_empty_database(dashboard_app):
    """Verify default zero values for dashboard stats on an empty database."""
    with dashboard_app.app_context():
        stats = get_dashboard_stats(db.session)

        kpis = stats["kpis"]
        assert kpis["total_transactions"] == 0
        assert kpis["total_alerts"] == 0
        assert kpis["open_alerts"] == 0
        assert kpis["pending_cases"] == 0
        assert kpis["escalated_cases"] == 0
        assert kpis["closed_cases"] == 0

        assert "LOW" in stats["risk_distribution"]
        assert "CRITICAL" in stats["risk_distribution"]
        assert "CRITICAL" in stats["alert_priorities"]
        assert stats["recent_suspicious_transactions"] == []


def test_get_dashboard_stats_populated_data(dashboard_app):
    """Verify accurate aggregation of KPIs and metrics with populated database entities."""
    with dashboard_app.app_context():
        now = utc_now()
        analyst = _setup_analyst_user("metrics_analyst")

        # 1. Customer and Account
        customer = Customer(
            customer_reference="CUST-001",
            first_name="Jane",
            last_name="Doe",
            country_code="US",
            risk_segment=CustomerRiskSegment.STANDARD,
            onboarding_date=now.date(),
        )
        db.session.add(customer)
        db.session.flush()

        debit_acc = Account(
            account_number="ACC-DEBIT-001",
            customer_id=customer.id,
            account_type=AccountType.CHECKING,
            currency=CurrencyCode.USD,
            status=AccountStatus.ACTIVE,
            balance=Decimal("15000.00"),
            overdraft_limit=Decimal("0.00"),
            opened_at=now,
        )
        db.session.add(debit_acc)
        db.session.flush()

        # 2. Risk Rule
        rule = RiskRule(
            code="CIRCULAR_FUND_TRANSFER",
            version=1,
            name="Circular Fund Transfer",
            description="Closed loop transfer detected across internal accounts",
            category="AML",
            severity=RiskSeverity.CRITICAL,
            score_weight=30,
            configuration={"window_hours": 24},
            is_active=True,
            effective_from=now,
        )
        db.session.add(rule)
        db.session.flush()

        # 3. Create Transactions & Risk Assessments
        # Transaction 1: Critical alerting transaction
        txn1 = Transaction(
            transaction_reference="TXN-ALERT-001",
            debit_account_id=debit_acc.id,
            transaction_type=TransactionType.OUTGOING,
            status=TransactionStatus.POSTED,
            amount=Decimal("75000.00"),
            currency=CurrencyCode.USD,
            occurred_at=now,
            debit_account_status_snapshot=AccountStatus.ACTIVE,
        )
        db.session.add(txn1)
        db.session.flush()

        ass1 = RiskAssessment(
            transaction_id=txn1.id,
            model_version="v1.0.1",
            score=85,
            risk_level=RiskLevel.CRITICAL,
            assessed_at=now,
        )
        db.session.add(ass1)
        db.session.flush()

        finding1 = RiskFinding(
            assessment_id=ass1.id,
            rule_id=rule.id,
            rule_code=rule.code,
            score=30,
            severity=RiskSeverity.CRITICAL,
            explanation="Circular loop detected",
        )
        db.session.add(finding1)
        db.session.flush()

        alert1 = Alert(
            alert_reference="ALT-001",
            transaction_id=txn1.id,
            assessment_id=ass1.id,
            finding_id=finding1.id,
            triggering_rule_id=rule.id,
            status=AlertStatus.OPEN,
            priority=AlertPriority.CRITICAL,
            score=85,
            summary="Critical circular transfer alert",
        )
        db.session.add(alert1)

        # Transaction 2: Low-risk non-alerting transaction
        txn2 = Transaction(
            transaction_reference="TXN-LOW-002",
            debit_account_id=debit_acc.id,
            transaction_type=TransactionType.OUTGOING,
            status=TransactionStatus.POSTED,
            amount=Decimal("25.00"),
            currency=CurrencyCode.USD,
            occurred_at=now,
            debit_account_status_snapshot=AccountStatus.ACTIVE,
        )
        db.session.add(txn2)
        db.session.flush()

        ass2 = RiskAssessment(
            transaction_id=txn2.id,
            model_version="v1.0.1",
            score=0,
            risk_level=RiskLevel.LOW,
            assessed_at=now,
        )
        db.session.add(ass2)

        # 4. Create Cases
        case_pending = Case(
            case_reference="CASE-001",
            title="Suspicious Outgoing Spike",
            status=CaseStatus.IN_REVIEW,
            priority=CasePriority.HIGH,
            opened_by_user_id=analyst.id,
            opened_at=now,
        )
        case_escalated = Case(
            case_reference="CASE-002",
            title="Confirmed Circular Transfer Loop",
            status=CaseStatus.ESCALATED,
            priority=CasePriority.CRITICAL,
            opened_by_user_id=analyst.id,
            opened_at=now,
        )
        case_closed = Case(
            case_reference="CASE-003",
            title="Resolved False Positive",
            status=CaseStatus.CLOSED,
            priority=CasePriority.LOW,
            opened_by_user_id=analyst.id,
            opened_at=now,
            closed_by_user_id=analyst.id,
            closed_at=now,
        )
        db.session.add_all([case_pending, case_escalated, case_closed])
        db.session.commit()

        # Run stats calculation
        stats = get_dashboard_stats(db.session)

        # Verify KPIs
        assert stats["kpis"]["total_transactions"] == 2
        assert stats["kpis"]["total_alerts"] == 1
        assert stats["kpis"]["open_alerts"] == 1
        assert stats["kpis"]["pending_cases"] == 1
        assert stats["kpis"]["escalated_cases"] == 1
        assert stats["kpis"]["closed_cases"] == 1

        # Verify distributions
        assert stats["risk_distribution"]["CRITICAL"] == 1
        assert stats["risk_distribution"]["LOW"] == 1
        assert stats["alert_priorities"]["CRITICAL"] == 1
        assert stats["alert_statuses"]["OPEN"] == 1

        # Verify recent suspicious transactions
        assert len(stats["recent_suspicious_transactions"]) == 1
        recent = stats["recent_suspicious_transactions"][0]
        assert recent["alert_reference"] == "ALT-001"
        assert recent["transaction_reference"] == "TXN-ALERT-001"
        assert recent["score"] == 85
        assert recent["priority"] == "CRITICAL"
        assert recent["status"] == "OPEN"
        assert recent["customer_name"] == "Jane Doe"


def test_dashboard_stats_scope_to_model_version_and_dedupe(dashboard_app):
    """Metrics use one model version and list each suspicious transaction once."""
    with dashboard_app.app_context():
        now = utc_now()
        _setup_analyst_user("version_analyst")

        customer = Customer(
            customer_reference="CUST-VERSION-001",
            first_name="Model",
            last_name="Scope",
            country_code="US",
            risk_segment=CustomerRiskSegment.STANDARD,
            onboarding_date=now.date(),
        )
        db.session.add(customer)
        db.session.flush()

        account = Account(
            account_number="ACC-VERSION-001",
            customer_id=customer.id,
            account_type=AccountType.CHECKING,
            currency=CurrencyCode.USD,
            status=AccountStatus.ACTIVE,
            balance=Decimal("10000.00"),
            overdraft_limit=Decimal("0.00"),
            opened_at=now,
        )
        db.session.add(account)
        db.session.flush()

        rule = RiskRule(
            code="VERSION_SCOPE_RULE",
            version=1,
            name="Version Scope Rule",
            description="Rule used to verify dashboard model-version scoping",
            category="AML",
            severity=RiskSeverity.CRITICAL,
            score_weight=30,
            configuration={},
            is_active=True,
            effective_from=now,
        )
        db.session.add(rule)
        db.session.flush()

        secondary_rule = RiskRule(
            code="VERSION_SCOPE_RULE_2",
            version=1,
            name="Secondary Version Scope Rule",
            description="Second rule used to create a duplicate transaction alert",
            category="AML",
            severity=RiskSeverity.HIGH,
            score_weight=20,
            configuration={},
            is_active=True,
            effective_from=now,
        )
        db.session.add(secondary_rule)
        db.session.flush()

        def make_transaction(reference: str, occurred_at):
            transaction = Transaction(
                transaction_reference=reference,
                debit_account_id=account.id,
                transaction_type=TransactionType.OUTGOING,
                status=TransactionStatus.POSTED,
                amount=Decimal("500.00"),
                currency=CurrencyCode.USD,
                occurred_at=occurred_at,
                debit_account_status_snapshot=AccountStatus.ACTIVE,
            )
            db.session.add(transaction)
            db.session.flush()
            return transaction

        def add_alert(
            transaction,
            *,
            model_version: str,
            alert_reference: str,
            score: int,
            risk_level: RiskLevel,
            assessed_at,
            rule: RiskRule,
        ):
            assessment = db.session.scalar(
                db.select(RiskAssessment).where(
                    RiskAssessment.transaction_id == transaction.id,
                    RiskAssessment.model_version == model_version,
                )
            )
            if assessment is None:
                assessment = RiskAssessment(
                    transaction_id=transaction.id,
                    model_version=model_version,
                    score=score,
                    risk_level=risk_level,
                    assessed_at=assessed_at,
                )
                db.session.add(assessment)
                db.session.flush()

            finding = RiskFinding(
                assessment_id=assessment.id,
                rule_id=rule.id,
                rule_code=rule.code,
                score=score,
                severity=RiskSeverity.CRITICAL,
                explanation="Scoped finding",
            )
            db.session.add(finding)
            db.session.flush()

            alert = Alert(
                alert_reference=alert_reference,
                transaction_id=transaction.id,
                assessment_id=assessment.id,
                finding_id=finding.id,
                triggering_rule_id=rule.id,
                status=AlertStatus.OPEN,
                priority=AlertPriority.CRITICAL,
                score=score,
                summary="Scoped alert",
            )
            db.session.add(alert)
            return alert

        txn_new = make_transaction("TXN-VERSION-NEW", now)
        add_alert(
            txn_new,
            model_version="v1.0.1",
            alert_reference="ALT-VERSION-NEW-1",
            score=85,
            risk_level=RiskLevel.CRITICAL,
            assessed_at=now,
            rule=rule,
        )
        add_alert(
            txn_new,
            model_version="v1.0.1",
            alert_reference="ALT-VERSION-NEW-2",
            score=85,
            risk_level=RiskLevel.CRITICAL,
            assessed_at=now,
            rule=secondary_rule,
        )

        txn_low = make_transaction("TXN-VERSION-LOW", now)
        db.session.add(
            RiskAssessment(
                transaction_id=txn_low.id,
                model_version="v1.0.1",
                score=0,
                risk_level=RiskLevel.LOW,
                assessed_at=now,
            )
        )

        txn_old = make_transaction("TXN-VERSION-OLD", now)
        add_alert(
            txn_old,
            model_version="v1.0.0",
            alert_reference="ALT-VERSION-OLD",
            score=90,
            risk_level=RiskLevel.CRITICAL,
            assessed_at=now,
            rule=rule,
        )
        db.session.commit()

        stats = get_dashboard_stats(
            db.session,
            model_version="v1.0.1",
            reference_date="2026-10-30",
            alert_threshold=40,
        )

        assert stats["model_version"] == "v1.0.1"
        assert stats["reference_date"] == "2026-10-30"
        assert stats["alert_threshold"] == 40
        assert stats["kpis"]["total_transactions"] == 3
        assert stats["kpis"]["total_alerts"] == 2
        assert stats["kpis"]["open_alerts"] == 2
        assert stats["risk_distribution"]["CRITICAL"] == 1
        assert stats["risk_distribution"]["LOW"] == 1
        assert stats["risk_distribution_percentages"]["CRITICAL"] == 50.0
        assert stats["risk_distribution_percentages"]["LOW"] == 50.0
        assert len(stats["recent_suspicious_transactions"]) == 1
        assert (
            stats["recent_suspicious_transactions"][0]["transaction_reference"]
            == "TXN-VERSION-NEW"
        )

        old_stats = get_dashboard_stats(db.session, model_version="v1.0.0")
        assert old_stats["kpis"]["total_alerts"] == 1
        assert old_stats["risk_distribution"]["CRITICAL"] == 1
        assert old_stats["risk_distribution"]["LOW"] == 0
        assert old_stats["risk_distribution_percentages"]["CRITICAL"] == 100.0
        assert len(old_stats["recent_suspicious_transactions"]) == 1
        assert (
            old_stats["recent_suspicious_transactions"][0]["alert_reference"]
            == "ALT-VERSION-OLD"
        )


def test_dashboard_web_view_authenticated(dashboard_app, dashboard_client):
    """GET /dashboard authenticated renders the dashboard HTML view."""
    with dashboard_app.app_context():
        _setup_analyst_user("web_analyst")

    dashboard_client.post(
        "/login",
        data={"username": "web_analyst", "password": "SecurePassword123!"},
    )

    response = dashboard_client.get("/dashboard")
    assert response.status_code == 200
    assert b"Risk Operations Dashboard" in response.data
    assert b"Transactions" in response.data
    assert b"Total Alerts" in response.data
    assert b"Open Alerts" in response.data
    assert b"Pending Cases" in response.data
    assert b"Recently Detected Suspicious Transactions" in response.data
    assert b"Model v1.0.1" in response.data
    assert b"2026-10-30" in response.data
    assert b"<strong>40</strong>" in response.data


def test_dashboard_stats_api_authenticated(dashboard_app, dashboard_client):
    """GET /api/v1/dashboard/stats authenticated returns valid JSON statistics."""
    with dashboard_app.app_context():
        _setup_analyst_user("api_analyst")

    dashboard_client.post(
        "/login",
        data={"username": "api_analyst", "password": "SecurePassword123!"},
    )

    response = dashboard_client.get("/api/v1/dashboard/stats")
    assert response.status_code == 200
    assert response.is_json

    data = response.get_json()
    assert "kpis" in data
    assert "risk_distribution" in data
    assert "alert_priorities" in data
    assert "alert_statuses" in data
    assert "recent_suspicious_transactions" in data


def test_ground_truth_isolation(dashboard_app):
    """Assert ground truth and evaluation schema are completely isolated from dashboard code."""
    import inspect

    import app.blueprints.dashboard.routes as dashboard_routes
    import app.services.dashboard as dashboard_service

    # Inspect source code of dashboard service and routes
    service_src = inspect.getsource(dashboard_service)
    routes_src = inspect.getsource(dashboard_routes)

    assert "ground_truth" not in service_src.lower()
    assert "yottaflex_eval" not in service_src.lower()
    assert "groundtruth" not in service_src
    assert "evaluation" not in service_src.lower()

    assert "ground_truth" not in routes_src.lower()
    assert "yottaflex_eval" not in routes_src.lower()
    assert "groundtruth" not in routes_src

    # Verify app config has no eval binds
    assert "eval" not in dashboard_app.config.get("SQLALCHEMY_BINDS", {})
