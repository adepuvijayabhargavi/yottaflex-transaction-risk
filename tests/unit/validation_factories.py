"""Factories for validation-service tests."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from itertools import count
from typing import TypeVar

from sqlalchemy.orm import Session

from app.models import (
    Account,
    Alert,
    AuditEvent,
    Case,
    CaseAlert,
    CaseDecision,
    CaseNote,
    Customer,
    DatasetRun,
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
    CustomerRiskSegment,
    DatasetRunStatus,
    DeviceType,
    MerchantRiskLevel,
    RiskLevel,
    RiskSeverity,
    TransactionStatus,
    TransactionType,
    TransferStatus,
    UserRole,
    ValidationResolutionStatus,
    ValidationSeverity,
)

BASE_TIME = datetime(2025, 1, 1, 12, 0, 0)
_SUFFIXES = count(1)
T = TypeVar("T")


def _suffix() -> str:
    return f"{next(_SUFFIXES):06d}"


def _save(session: Session, value: T, add: bool) -> T:
    if add:
        session.add(value)
        session.flush()
    return value


def make_user(
    session: Session,
    *,
    add: bool = True,
    suffix: str | None = None,
) -> User:
    value = _suffix() if suffix is None else suffix
    return _save(
        session,
        User(
            username=f"analyst-{value}",
            email=f"analyst-{value}@example.com",
            password_hash="test-password-hash",
            full_name="Test Analyst",
            role=UserRole.ANALYST,
        ),
        add,
    )


def make_customer(
    session: Session,
    *,
    add: bool = True,
    suffix: str | None = None,
) -> Customer:
    value = _suffix() if suffix is None else suffix
    return _save(
        session,
        Customer(
            customer_reference=f"CUST-{value}",
            first_name="Test",
            last_name="Customer",
            country_code="US",
            risk_segment=CustomerRiskSegment.STANDARD,
            onboarding_date=date(2024, 1, 1),
        ),
        add,
    )


def make_merchant(
    session: Session,
    *,
    add: bool = True,
    suffix: str | None = None,
) -> Merchant:
    value = _suffix() if suffix is None else suffix
    return _save(
        session,
        Merchant(
            merchant_reference=f"MER-{value}",
            name=f"Merchant {value}",
            country_code="US",
            risk_level=MerchantRiskLevel.STANDARD,
        ),
        add,
    )


def make_device(
    session: Session,
    customer: Customer,
    *,
    add: bool = True,
    suffix: str | None = None,
    first_seen_at: datetime | None = None,
    last_seen_at: datetime | None = None,
) -> Device:
    value = _suffix() if suffix is None else suffix
    return _save(
        session,
        Device(
            device_fingerprint=f"DEVICE-{value}",
            customer_id=customer.id,
            device_type=DeviceType.MOBILE,
            first_seen_at=first_seen_at or BASE_TIME,
            last_seen_at=last_seen_at or BASE_TIME + timedelta(hours=1),
        ),
        add,
    )


def make_account(
    session: Session,
    customer: Customer,
    *,
    add: bool = True,
    suffix: str | None = None,
    status: AccountStatus = AccountStatus.ACTIVE,
    balance: Decimal = Decimal("100.00"),
    overdraft_limit: Decimal = Decimal("0.00"),
    currency: CurrencyCode = CurrencyCode.USD,
    opened_at: datetime | None = None,
    closed_at: datetime | None = None,
) -> Account:
    value = _suffix() if suffix is None else suffix
    opened = opened_at or BASE_TIME
    if status == AccountStatus.CLOSED and closed_at is None:
        closed_at = opened + timedelta(hours=2)
    return _save(
        session,
        Account(
            account_number=f"ACC-{value}",
            customer_id=customer.id,
            account_type=AccountType.CHECKING,
            currency=currency,
            status=status,
            balance=balance,
            overdraft_limit=overdraft_limit,
            opened_at=opened,
            closed_at=closed_at,
        ),
        add,
    )


def make_transaction(
    session: Session,
    *,
    add: bool = True,
    suffix: str | None = None,
    debit_account: Account | None = None,
    credit_account: Account | None = None,
    transaction_type: TransactionType = TransactionType.OUTGOING,
    amount: Decimal = Decimal("100.00"),
    currency: CurrencyCode = CurrencyCode.USD,
    occurred_at: datetime | None = None,
    status: TransactionStatus = TransactionStatus.POSTED,
    transfer_group_id: int | None = None,
    merchant_id: int | None = None,
    device_id: int | None = None,
    debit_snapshot: AccountStatus | None = AccountStatus.ACTIVE,
    credit_snapshot: AccountStatus | None = AccountStatus.ACTIVE,
) -> Transaction:
    value = _suffix() if suffix is None else suffix
    return _save(
        session,
        Transaction(
            transaction_reference=f"TX-{value}",
            debit_account_id=debit_account.id if debit_account else None,
            credit_account_id=credit_account.id if credit_account else None,
            transfer_group_id=transfer_group_id,
            merchant_id=merchant_id,
            device_id=device_id,
            transaction_type=transaction_type,
            status=status,
            amount=amount,
            currency=currency,
            occurred_at=occurred_at or BASE_TIME + timedelta(hours=1),
            debit_account_status_snapshot=debit_snapshot if debit_account else None,
            credit_account_status_snapshot=(
                credit_snapshot if credit_account else None
            ),
        ),
        add,
    )


def make_transfer_group(
    session: Session,
    customer: Customer,
    *,
    add: bool = True,
    suffix: str | None = None,
    status: TransferStatus = TransferStatus.RECONCILED,
    expected_total: Decimal = Decimal("100.00"),
    actual_total: Decimal = Decimal("100.00"),
    currency: CurrencyCode = CurrencyCode.USD,
    reconciled_at: datetime | None = None,
) -> TransferGroup:
    value = _suffix() if suffix is None else suffix
    return _save(
        session,
        TransferGroup(
            transfer_reference=f"TRF-{value}",
            initiated_by_customer_id=customer.id,
            status=status,
            expected_total=expected_total,
            actual_total=actual_total,
            currency=currency,
            reconciled_at=reconciled_at or BASE_TIME + timedelta(hours=2),
            created_at=BASE_TIME,
        ),
        add,
    )


def make_rule(
    session: Session,
    *,
    add: bool = True,
    suffix: str | None = None,
    code: str | None = None,
) -> RiskRule:
    value = _suffix() if suffix is None else suffix
    return _save(
        session,
        RiskRule(
            code=code or f"RULE-{value}",
            version=1,
            name=f"Rule {value}",
            category="test",
            severity=RiskSeverity.HIGH,
            score_weight=10,
            configuration={},
            effective_from=BASE_TIME,
        ),
        add,
    )


def make_assessment(
    session: Session,
    transaction: Transaction,
    *,
    add: bool = True,
    suffix: str | None = None,
    score: int = 50,
) -> RiskAssessment:
    value = _suffix() if suffix is None else suffix
    return _save(
        session,
        RiskAssessment(
            transaction_id=transaction.id,
            model_version=f"model-{value}",
            score=score,
            risk_level=RiskLevel.HIGH,
            status=AssessmentStatus.COMPLETED,
            assessed_at=BASE_TIME + timedelta(hours=2),
        ),
        add,
    )


def make_finding(
    session: Session,
    assessment: RiskAssessment,
    rule: RiskRule,
    *,
    add: bool = True,
    rule_code: str | None = None,
) -> RiskFinding:
    return _save(
        session,
        RiskFinding(
            assessment_id=assessment.id,
            rule_id=rule.id,
            rule_code=rule_code or rule.code,
            score=50,
            severity=RiskSeverity.HIGH,
            explanation="Test finding",
            created_at=BASE_TIME + timedelta(hours=2, minutes=30),
        ),
        add,
    )


def make_alert(
    session: Session,
    transaction: Transaction,
    assessment: RiskAssessment,
    finding: RiskFinding,
    rule: RiskRule,
    *,
    add: bool = True,
    suffix: str | None = None,
) -> Alert:
    value = _suffix() if suffix is None else suffix
    return _save(
        session,
        Alert(
            alert_reference=f"ALERT-{value}",
            transaction_id=transaction.id,
            assessment_id=assessment.id,
            finding_id=finding.id,
            triggering_rule_id=rule.id,
            status=AlertStatus.OPEN,
            priority=AlertPriority.HIGH,
            score=50,
            summary="Test alert",
            created_at=BASE_TIME + timedelta(hours=3),
        ),
        add,
    )


def make_case(
    session: Session,
    user: User,
    *,
    add: bool = True,
    suffix: str | None = None,
    status: CaseStatus = CaseStatus.OPEN,
    closed_at: datetime | None = None,
) -> Case:
    value = _suffix() if suffix is None else suffix
    return _save(
        session,
        Case(
            case_reference=f"CASE-{value}",
            title=f"Case {value}",
            status=status,
            priority=CasePriority.MEDIUM,
            opened_by_user_id=user.id,
            opened_at=BASE_TIME + timedelta(hours=4),
            closed_at=closed_at,
        ),
        add,
    )


def make_case_alert(
    session: Session,
    case: Case,
    alert: Alert,
    user: User,
    *,
    add: bool = True,
    linked_at: datetime | None = None,
    unlinked_at: datetime | None = None,
    unlinked_by_user_id: int | None = None,
    unlink_reason: str | None = None,
) -> CaseAlert:
    return _save(
        session,
        CaseAlert(
            case_id=case.id,
            alert_id=alert.id,
            linked_by_user_id=user.id,
            linked_at=linked_at or BASE_TIME + timedelta(hours=5),
            unlinked_at=unlinked_at,
            unlinked_by_user_id=unlinked_by_user_id,
            unlink_reason=unlink_reason,
        ),
        add,
    )


def make_case_note(
    session: Session,
    case: Case,
    user: User,
    *,
    add: bool = True,
    body: str = "Investigation note",
) -> CaseNote:
    return _save(
        session,
        CaseNote(
            case_id=case.id,
            author_user_id=user.id,
            note_type=CaseNoteType.INVESTIGATION,
            body=body,
            noted_at=BASE_TIME + timedelta(hours=5, minutes=30),
        ),
        add,
    )


def make_case_decision(
    session: Session,
    case: Case,
    user: User,
    alert: Alert,
    *,
    add: bool = True,
    decided_at: datetime | None = None,
    rationale: str = "Validated decision",
) -> CaseDecision:
    return _save(
        session,
        CaseDecision(
            case_id=case.id,
            decided_by_user_id=user.id,
            decision=CaseDecisionType.MONITOR,
            rationale=rationale,
            decided_at=decided_at or BASE_TIME + timedelta(hours=6),
            triggering_alert_id=alert.id,
        ),
        add,
    )


def make_dataset_run(
    session: Session,
    *,
    add: bool = True,
    suffix: str | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> DatasetRun:
    value = _suffix() if suffix is None else suffix
    return _save(
        session,
        DatasetRun(
            run_reference=f"RUN-{value}",
            profile_name="pilot",
            seed=42,
            status=DatasetRunStatus.COMPLETED,
            reference_datetime_utc=BASE_TIME,
            record_counts={},
            checksums={},
            started_at=started_at or BASE_TIME,
            completed_at=completed_at or BASE_TIME + timedelta(hours=1),
        ),
        add,
    )


def make_validation_event(
    session: Session,
    *,
    add: bool = True,
    suffix: str | None = None,
    resolution_status: ValidationResolutionStatus = ValidationResolutionStatus.OPEN,
    resolved_at: datetime | None = None,
    resolved_by_user_id: int | None = None,
) -> ValidationEvent:
    value = _suffix() if suffix is None else suffix
    return _save(
        session,
        ValidationEvent(
            event_reference=f"VAL-TEST-{value}",
            validation_code="TEST_EVENT",
            severity=ValidationSeverity.ERROR,
            entity_type="transaction",
            message="Test validation event",
            resolution_status=resolution_status,
            resolved_at=resolved_at,
            resolved_by_user_id=resolved_by_user_id,
        ),
        add,
    )


def make_audit_event(
    session: Session,
    *,
    add: bool = True,
    actor_user_id: int | None = None,
) -> AuditEvent:
    return _save(
        session,
        AuditEvent(
            event_type="TEST",
            entity_type="case",
            entity_id=1,
            actor_user_id=actor_user_id,
            summary="Test audit event",
            occurred_at=BASE_TIME,
        ),
        add,
    )
