"""Read-only transaction investigation routes and service tests."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func

from app import create_app
from app.extensions import db
from app.models import (
    Account,
    AccountStatusHistory,
    Alert,
    AuditEvent,
    Base,
    Customer,
    Device,
    Merchant,
    RiskAssessment,
    RiskFinding,
    RiskRule,
    Transaction,
    TransferGroup,
    User,
    ValidationEvent,
)
from app.models.base import utc_now
from app.models.enums import (
    AccountStatus,
    AccountType,
    AlertPriority,
    AlertStatus,
    AssessmentStatus,
    CurrencyCode,
    DeviceType,
    RiskLevel,
    RiskSeverity,
    TransactionStatus,
    TransactionType,
    TransferStatus,
    UserRole,
    ValidationResolutionStatus,
    ValidationSeverity,
)
from app.services.transactions import (
    get_account_transaction_history,
    get_transaction_investigation,
)


@pytest.fixture()
def transactions_app():
    test_app = create_app("testing")
    with test_app.app_context():
        Base.metadata.create_all(db.engine)
        yield test_app
        db.session.remove()
        Base.metadata.drop_all(db.engine)


@pytest.fixture()
def transactions_client(transactions_app):
    return transactions_app.test_client()


def _create_user(role: UserRole = UserRole.ANALYST) -> User:
    user = User(
        username=f"investigator_{role.value.lower()}",
        email=f"investigator_{role.value.lower()}@yottaflex.bank",
        full_name=f"Investigator {role.value.title()}",
        role=role,
        is_active=True,
    )
    user.set_password("SecurePassword123!")
    db.session.add(user)
    db.session.flush()
    return user


def _create_transaction(
    reference: str,
    *,
    now,
    debit_account_id: int | None,
    credit_account_id: int | None,
    transaction_type: TransactionType,
    amount: str,
    transfer_group_id: int | None = None,
    merchant_id: int | None = None,
    device_id: int | None = None,
    occurred_minutes: int = 0,
) -> Transaction:
    transaction = Transaction(
        transaction_reference=reference,
        transfer_group_id=transfer_group_id,
        debit_account_id=debit_account_id,
        credit_account_id=credit_account_id,
        merchant_id=merchant_id,
        device_id=device_id,
        transaction_type=transaction_type,
        status=TransactionStatus.POSTED,
        amount=Decimal(amount),
        currency=CurrencyCode.USD,
        occurred_at=now + timedelta(minutes=occurred_minutes),
        description=f"Investigation detail for {reference}",
        debit_account_status_snapshot=(
            AccountStatus.ACTIVE if debit_account_id is not None else None
        ),
        credit_account_status_snapshot=(
            AccountStatus.ACTIVE if credit_account_id is not None else None
        ),
    )
    db.session.add(transaction)
    db.session.flush()
    return transaction


def _seed_investigation():
    now = utc_now()
    analyst = _create_user()
    customer = Customer(
        customer_reference="CUST-INV-1",
        first_name="Alex",
        last_name="Investigation",
        country_code="US",
        onboarding_date=now.date(),
    )
    other_customer = Customer(
        customer_reference="CUST-INV-2",
        first_name="Sam",
        last_name="Other",
        country_code="US",
        onboarding_date=now.date(),
    )
    db.session.add_all([customer, other_customer])
    db.session.flush()

    account_one = Account(
        account_number="ACC-INV-1",
        customer_id=customer.id,
        account_type=AccountType.CHECKING,
        currency=CurrencyCode.USD,
        status=AccountStatus.ACTIVE,
        balance=Decimal("1000.00"),
        overdraft_limit=Decimal("0.00"),
        opened_at=now - timedelta(days=365),
    )
    account_two = Account(
        account_number="ACC-INV-2",
        customer_id=customer.id,
        account_type=AccountType.SAVINGS,
        currency=CurrencyCode.USD,
        status=AccountStatus.ACTIVE,
        balance=Decimal("2000.00"),
        overdraft_limit=Decimal("0.00"),
        opened_at=now - timedelta(days=300),
    )
    account_three = Account(
        account_number="ACC-INV-3",
        customer_id=other_customer.id,
        account_type=AccountType.CHECKING,
        currency=CurrencyCode.USD,
        status=AccountStatus.ACTIVE,
        balance=Decimal("500.00"),
        overdraft_limit=Decimal("0.00"),
        opened_at=now - timedelta(days=200),
    )
    db.session.add_all([account_one, account_two, account_three])
    db.session.flush()

    merchant = Merchant(
        merchant_reference="MER-INV-1",
        name="Investigation Merchant",
        category="Retail",
        country_code="US",
    )
    device = Device(
        device_fingerprint="device-investigation-1",
        customer_id=customer.id,
        device_type=DeviceType.MOBILE,
        first_seen_at=now - timedelta(days=2),
        last_seen_at=now,
        is_trusted=False,
    )
    db.session.add_all([merchant, device])
    db.session.flush()

    group = TransferGroup(
        transfer_reference="TRF-INV-1",
        initiated_by_customer_id=customer.id,
        status=TransferStatus.RECONCILED,
        expected_total=Decimal("200.00"),
        actual_total=Decimal("200.00"),
        currency=CurrencyCode.USD,
        reconciled_at=now + timedelta(minutes=10),
    )
    db.session.add(group)
    db.session.flush()

    target = _create_transaction(
        "TX-INV-TARGET",
        now=now,
        debit_account_id=account_one.id,
        credit_account_id=account_two.id,
        transaction_type=TransactionType.INTERNAL,
        amount="100.00",
        transfer_group_id=group.id,
        merchant_id=merchant.id,
        device_id=device.id,
    )
    transfer_leg = _create_transaction(
        "TX-INV-TRANSFER-LEG",
        now=now,
        debit_account_id=account_two.id,
        credit_account_id=account_one.id,
        transaction_type=TransactionType.INTERNAL,
        amount="100.00",
        transfer_group_id=group.id,
        merchant_id=merchant.id,
        device_id=device.id,
        occurred_minutes=1,
    )
    debit_transaction = _create_transaction(
        "TX-INV-DEBIT",
        now=now,
        debit_account_id=account_one.id,
        credit_account_id=None,
        transaction_type=TransactionType.OUTGOING,
        amount="25.00",
        occurred_minutes=2,
    )
    credit_transaction = _create_transaction(
        "TX-INV-CREDIT",
        now=now,
        debit_account_id=None,
        credit_account_id=account_one.id,
        transaction_type=TransactionType.INCOMING,
        amount="50.00",
        occurred_minutes=3,
    )
    evidence_transaction = _create_transaction(
        "TX-INV-EVIDENCE",
        now=now,
        debit_account_id=account_three.id,
        credit_account_id=None,
        transaction_type=TransactionType.OUTGOING,
        amount="75.00",
        occurred_minutes=4,
    )

    rule = RiskRule(
        code="INVESTIGATION_RULE",
        version=1,
        name="Investigation rule",
        description="A test rule used for investigation display.",
        category="TEST",
        severity=RiskSeverity.HIGH,
        score_weight=55,
        configuration={},
        is_active=True,
        effective_from=now,
    )
    db.session.add(rule)
    db.session.flush()
    assessment = RiskAssessment(
        transaction_id=target.id,
        model_version="test-v1",
        score=55,
        risk_level=RiskLevel.HIGH,
        status=AssessmentStatus.COMPLETED,
        assessed_at=now + timedelta(minutes=5),
        explanation={"summary": "Stored high-risk assessment", "score": 55},
    )
    db.session.add(assessment)
    db.session.flush()
    finding = RiskFinding(
        assessment_id=assessment.id,
        rule_id=rule.id,
        rule_code=rule.code,
        score=55,
        severity=RiskSeverity.HIGH,
        explanation="A stored finding explains the elevated activity.",
        evidence={
            "cluster_transaction_references": [
                debit_transaction.transaction_reference,
                evidence_transaction.transaction_reference,
            ]
        },
        created_at=now + timedelta(minutes=6),
    )
    db.session.add(finding)
    db.session.flush()
    alert = Alert(
        alert_reference="ALT-INV-1",
        transaction_id=target.id,
        assessment_id=assessment.id,
        finding_id=finding.id,
        triggering_rule_id=rule.id,
        status=AlertStatus.ACKNOWLEDGED,
        priority=AlertPriority.HIGH,
        score=55,
        summary="Investigation test alert",
        acknowledged_at=now + timedelta(minutes=7),
    )
    db.session.add(alert)
    db.session.flush()
    audit_event = AuditEvent(
        event_type="ALERT_ACKNOWLEDGED",
        entity_type="alert",
        entity_id=alert.id,
        actor_user_id=analyst.id,
        summary="Alert acknowledged for review",
        occurred_at=now + timedelta(minutes=8),
    )
    validation_event = ValidationEvent(
        event_reference="VAL-INV-1",
        validation_code="INVESTIGATION_VALIDATION",
        severity=ValidationSeverity.WARNING,
        entity_type="transaction",
        entity_id=target.id,
        transaction_id=target.id,
        message="A recorded validation warning for this transaction.",
        resolution_status=ValidationResolutionStatus.OPEN,
        created_at=now + timedelta(minutes=9),
    )
    db.session.add_all([audit_event, validation_event])
    db.session.commit()
    return {
        "analyst": analyst,
        "customer": customer,
        "account_one": account_one,
        "account_two": account_two,
        "target": target,
        "transfer_leg": transfer_leg,
        "debit_transaction": debit_transaction,
        "credit_transaction": credit_transaction,
        "evidence_transaction": evidence_transaction,
        "assessment": assessment,
        "finding": finding,
        "alert": alert,
    }


def _login(client, user_id: int) -> None:
    with client.session_transaction() as browser_session:
        browser_session["_user_id"] = str(user_id)
        browser_session["_fresh"] = True


def test_transaction_detail_requires_authentication(transactions_client):
    response = transactions_client.get("/transactions/1")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_transaction_lookup_page_and_exact_reference_redirect(transactions_app):
    with transactions_app.app_context():
        data = _seed_investigation()
        user_id = data["analyst"].id
        transaction_id = data["target"].id

    client = transactions_app.test_client()
    _login(client, user_id)
    search_page = client.get("/transactions/")
    result = client.get("/transactions/?q=TX-INV-TARGET", follow_redirects=False)
    result_by_id = client.get(
        f"/transactions/?q={transaction_id}", follow_redirects=False
    )
    missing = client.get("/transactions/?q=TX-UNKNOWN")

    assert search_page.status_code == 200
    assert b"Search by exact transaction reference" in search_page.data
    assert result.status_code == 302
    assert result.headers["Location"].endswith(f"/transactions/{transaction_id}")
    assert result_by_id.status_code == 302
    assert result_by_id.headers["Location"].endswith(f"/transactions/{transaction_id}")
    assert missing.status_code == 200
    assert b"No transaction matches" in missing.data


@pytest.mark.parametrize(
    "role",
    [UserRole.ANALYST, UserRole.SUPERVISOR, UserRole.ADMIN],
)
def test_transaction_detail_is_available_to_review_roles(transactions_app, role):
    with transactions_app.app_context():
        data = _seed_investigation()
        user = data["analyst"] if role is UserRole.ANALYST else _create_user(role)
        db.session.commit()
        user_id = user.id
        transaction_id = data["target"].id

    client = transactions_app.test_client()
    _login(client, user_id)
    response = client.get(f"/transactions/{transaction_id}")

    assert response.status_code == 200
    assert b"Transaction TX-INV-TARGET" in response.data


def test_transaction_detail_shows_recorded_investigation_context(
    transactions_app,
):
    with transactions_app.app_context():
        data = _seed_investigation()
        transaction_id = data["target"].id
        alert_id = data["alert"].id
        user_id = data["analyst"].id

    client = transactions_app.test_client()
    _login(client, user_id)
    response = client.get(f"/transactions/{transaction_id}")

    assert response.status_code == 200
    for expected in (
        b"Risk findings",
        b"A stored finding explains the elevated activity.",
        b"Stored high-risk assessment",
        b"Recorded timeline",
        b"INVESTIGATION_VALIDATION",
        b"Alert acknowledged for review",
        b"Transfer relationship",
        b"TRF-INV-1",
        b"TX-INV-TRANSFER-LEG",
        b"Related transactions",
        b"Referenced by stored risk evidence",
        b"View account history",
        b"Current status: POSTED",
        b"not a recorded historical status change",
    ):
        assert expected in response.data
    assert f"/alerts/{alert_id}".encode() in response.data


def test_transfer_legs_are_bounded_stably_and_report_truncation(transactions_app):
    with transactions_app.app_context():
        data = _seed_investigation()
        target = data["target"]
        now = target.occurred_at
        for index in range(104):
            _create_transaction(
                f"TX-INV-EXTRA-{index:03d}",
                now=now,
                debit_account_id=data["account_one"].id,
                credit_account_id=data["account_two"].id,
                transaction_type=TransactionType.INTERNAL,
                amount="1.00",
                transfer_group_id=target.transfer_group_id,
                occurred_minutes=index + 2,
            )
        db.session.commit()

        investigation = get_transaction_investigation(db.session, target.id)

        assert investigation is not None
        legs = investigation["transfer_legs"]
        assert len(legs) == 100
        assert legs[0]["id"] == target.id
        assert [leg["occurred_at"] for leg in legs] == sorted(
            leg["occurred_at"] for leg in legs
        )
        assert investigation["transfer_legs_pagination"] == {
            "total": 106,
            "shown": 100,
            "limit": 100,
            "truncated": True,
        }

        client = transactions_app.test_client()
        _login(client, data["analyst"].id)
        response = client.get(f"/transactions/{target.id}")

        assert b"Showing 100 of 106 transfer legs" in response.data


def test_timeline_includes_recorded_account_status_and_separates_current_status(
    transactions_app,
):
    with transactions_app.app_context():
        data = _seed_investigation()
        history = AccountStatusHistory(
            account_id=data["account_one"].id,
            previous_status=AccountStatus.FROZEN,
            new_status=AccountStatus.ACTIVE,
            reason="Restriction review completed",
            changed_at=data["target"].occurred_at - timedelta(days=1),
        )
        db.session.add(history)
        db.session.commit()

        investigation = get_transaction_investigation(
            db.session,
            data["target"].id,
        )

        assert investigation is not None
        timeline = investigation["timeline"]
        status_event = next(
            event for event in timeline if event["source"] == "Account status history"
        )
        transaction_event = next(
            event for event in timeline if event["title"] == "Transaction occurred"
        )
        assert status_event["title"] == "Account status change recorded"
        assert "ACC-INV-1: FROZEN -> ACTIVE" in status_event["summary"]
        assert "Restriction review completed" in status_event["summary"]
        assert status_event["timestamp"] == history.changed_at.isoformat()
        assert "POSTED" not in transaction_event["summary"]
        assert investigation["transaction"]["status"] == "POSTED"
        assert not any(
            "status change" in event["title"].lower()
            and event["source"] == "Transaction"
            for event in timeline
        )


def test_transaction_detail_returns_404_for_missing_transaction(transactions_app):
    with transactions_app.app_context():
        user = _create_user()
        db.session.commit()
        user_id = user.id

    client = transactions_app.test_client()
    _login(client, user_id)

    assert client.get("/transactions/99999").status_code == 404


def test_account_history_includes_debits_and_credits_with_stable_pagination(
    transactions_app,
):
    with transactions_app.app_context():
        data = _seed_investigation()
        account_id = data["account_one"].id
        target_id = data["target"].id
        user_id = data["analyst"].id

        page_one = get_account_transaction_history(
            db.session,
            account_id,
            page=1,
            per_page=2,
        )
        page_two = get_account_transaction_history(
            db.session,
            account_id,
            page=2,
            per_page=2,
        )

        assert page_one is not None
        assert page_two is not None
        assert page_one["pagination"]["total"] == 4
        assert page_one["pagination"]["pages"] == 2
        assert {item["direction"] for item in page_one["items"]} == {
            "DEBIT",
            "CREDIT",
        }
        assert page_one["items"][0]["id"] != page_one["items"][1]["id"]
        assert len(page_two["items"]) == 2
        assert {item["id"] for item in page_one["items"] + page_two["items"]} == {
            target_id,
            data["transfer_leg"].id,
            data["debit_transaction"].id,
            data["credit_transaction"].id,
        }

    client = transactions_app.test_client()
    _login(client, user_id)
    response = client.get(f"/transactions/accounts/{account_id}?page=1&per_page=2")

    assert response.status_code == 200
    assert b"Account transaction history" in response.data
    assert b"TX-INV-CREDIT" in response.data
    assert b"TX-INV-DEBIT" in response.data
    assert b"Next" in response.data


def test_account_history_bounds_page_size_and_returns_404_for_unknown_account(
    transactions_app,
):
    with transactions_app.app_context():
        data = _seed_investigation()
        account_id = data["account_one"].id
        user_id = data["analyst"].id

        result = get_account_transaction_history(
            db.session,
            account_id,
            page="invalid",
            per_page=10_000,
        )
        assert result is not None
        assert result["pagination"]["per_page"] == 100
        assert get_account_transaction_history(db.session, 99999) is None

    client = transactions_app.test_client()
    _login(client, user_id)
    assert client.get("/transactions/accounts/99999").status_code == 404


def test_related_transactions_explain_relationships_and_respect_limit(
    transactions_app,
):
    with transactions_app.app_context():
        data = _seed_investigation()
        investigation = get_transaction_investigation(
            db.session,
            data["target"].id,
        )
        limited = get_transaction_investigation(
            db.session,
            data["target"].id,
            related_limit=1,
        )

        assert investigation is not None
        by_reference = {
            item["reference"]: set(item["reasons"])
            for item in investigation["related_transactions"]
        }
        assert by_reference["TX-INV-TRANSFER-LEG"] >= {
            "Same transfer group",
            "Shared account",
            "Same merchant",
            "Same device",
        }
        assert "Referenced by stored risk evidence" in by_reference["TX-INV-EVIDENCE"]
        assert "Shared account" in by_reference["TX-INV-DEBIT"]
        assert limited is not None
        assert len(limited["related_transactions"]) == 1


def test_investigation_queries_are_read_only(transactions_app):
    with transactions_app.app_context():
        data = _seed_investigation()
        transaction = db.session.get(Transaction, data["target"].id)
        assessment_id = data["assessment"].id
        finding_id = data["finding"].id
        assessment = db.session.get(RiskAssessment, assessment_id)
        finding = db.session.get(RiskFinding, finding_id)
        alert_count = db.session.scalar(db.select(func.count(AuditEvent.id)))
        original_state = (
            transaction.status,
            transaction.amount,
            assessment.score,
            assessment.explanation,
            finding.explanation,
            alert_count,
        )

        investigation = get_transaction_investigation(db.session, transaction.id)

        assert investigation is not None
        assert not db.session.new
        assert not db.session.dirty
        assert not db.session.deleted
        assert (
            transaction.status,
            transaction.amount,
            assessment.score,
            assessment.explanation,
            finding.explanation,
            db.session.scalar(db.select(func.count(AuditEvent.id))),
        ) == original_state


def test_transaction_and_account_pages_are_read_only_for_authenticated_user(
    transactions_app,
):
    with transactions_app.app_context():
        data = _seed_investigation()
        user_id = data["analyst"].id
        transaction_id = data["target"].id
        account_id = data["account_one"].id
        assessment_id = data["assessment"].id
        finding_id = data["finding"].id

    client = transactions_app.test_client()
    _login(client, user_id)
    assert client.get(f"/transactions/{transaction_id}").status_code == 200
    assert client.get(f"/transactions/accounts/{account_id}").status_code == 200

    with transactions_app.app_context():
        transaction = db.session.get(Transaction, transaction_id)
        assessment = db.session.get(RiskAssessment, assessment_id)
        finding = db.session.get(RiskFinding, finding_id)
        assert transaction.status is TransactionStatus.POSTED
        assert transaction.amount == Decimal("100.00")
        assert assessment.score == 55
        assert finding.explanation == "A stored finding explains the elevated activity."
        assert (
            db.session.scalar(
                db.select(func.count(AuditEvent.id)).where(
                    AuditEvent.entity_type == "transaction",
                    AuditEvent.entity_id == transaction_id,
                )
            )
            == 0
        )
