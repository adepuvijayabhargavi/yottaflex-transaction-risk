"""Alert queue, detail, and review workflow services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.models import (
    Account,
    Alert,
    AuditEvent,
    Customer,
    RiskAssessment,
    RiskFinding,
    RiskRule,
    Transaction,
    User,
)
from app.models.base import utc_now
from app.models.enums import AlertPriority, AlertStatus, RiskLevel, UserRole
from app.services.validation import (
    ValidationError,
    ValidationIssue,
    validate_audit_event,
)

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
MAX_SEARCH_LENGTH = 100
MAX_WORKFLOW_REASON_LENGTH = 500
REVIEW_ROLES = (UserRole.ANALYST, UserRole.SUPERVISOR, UserRole.ADMIN)


@dataclass(frozen=True)
class AlertFilters:
    """Normalized filters applied to the alert queue."""

    q: str = ""
    priority: AlertPriority | None = None
    status: AlertStatus | None = None
    risk_level: RiskLevel | None = None
    date_from: date | None = None
    date_to: date | None = None


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _iso_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _normalize_filters(
    *,
    q: str | None,
    priority: AlertPriority | None,
    status: AlertStatus | None,
    risk_level: RiskLevel | None,
    date_from: date | None,
    date_to: date | None,
) -> AlertFilters:
    search = (q or "").strip()[:MAX_SEARCH_LENGTH]
    start = date_from
    end = date_to
    if start and end and start > end:
        start, end = end, start
    return AlertFilters(
        q=search,
        priority=priority,
        status=status,
        risk_level=risk_level,
        date_from=start,
        date_to=end,
    )


def _filter_conditions(filters: AlertFilters) -> list[Any]:
    conditions: list[Any] = []

    if filters.q:
        term = f"%{filters.q}%"
        search_conditions = [
            Alert.alert_reference.ilike(term),
            Alert.summary.ilike(term),
            Transaction.transaction_reference.ilike(term),
            Transaction.description.ilike(term),
        ]
        if filters.q.isdigit():
            identifier = int(filters.q)
            search_conditions.extend(
                [
                    Alert.id == identifier,
                    Transaction.id == identifier,
                ]
            )
        conditions.append(or_(*search_conditions))

    if filters.priority is not None:
        conditions.append(Alert.priority == filters.priority)
    if filters.status is not None:
        conditions.append(Alert.status == filters.status)
    if filters.risk_level is not None:
        conditions.append(RiskAssessment.risk_level == filters.risk_level)
    if filters.date_from is not None:
        conditions.append(
            Alert.created_at >= datetime.combine(filters.date_from, time.min)
        )
    if filters.date_to is not None:
        conditions.append(
            Alert.created_at
            < datetime.combine(filters.date_to + timedelta(days=1), time.min)
        )

    return conditions


def _filtered_alert_ids(filters: AlertFilters):
    return (
        select(Alert.id)
        .join(Transaction, Alert.transaction_id == Transaction.id)
        .join(RiskAssessment, Alert.assessment_id == RiskAssessment.id)
        .where(*_filter_conditions(filters))
    )


def _list_load_options():
    return (
        joinedload(Alert.transaction)
        .joinedload(Transaction.debit_account)
        .joinedload(Account.customer),
        joinedload(Alert.transaction)
        .joinedload(Transaction.credit_account)
        .joinedload(Account.customer),
        joinedload(Alert.assessment),
        joinedload(Alert.triggering_rule),
        joinedload(Alert.assigned_to),
    )


def _detail_load_options():
    return (
        joinedload(Alert.transaction)
        .joinedload(Transaction.debit_account)
        .joinedload(Account.customer),
        joinedload(Alert.transaction)
        .joinedload(Transaction.credit_account)
        .joinedload(Account.customer),
        joinedload(Alert.assessment)
        .selectinload(RiskAssessment.findings)
        .joinedload(RiskFinding.rule),
        joinedload(Alert.finding).joinedload(RiskFinding.rule),
        joinedload(Alert.triggering_rule),
        joinedload(Alert.assigned_to),
    )


def _primary_customer(transaction: Transaction) -> Customer | None:
    if transaction.debit_account and transaction.debit_account.customer:
        return transaction.debit_account.customer
    if transaction.credit_account and transaction.credit_account.customer:
        return transaction.credit_account.customer
    return None


def _serialize_customer(customer: Customer | None) -> dict[str, Any] | None:
    if customer is None:
        return None
    return {
        "id": customer.id,
        "reference": customer.customer_reference,
        "name": f"{customer.first_name} {customer.last_name}".strip(),
        "email": customer.email,
        "phone": customer.phone,
        "country_code": customer.country_code,
        "risk_segment": _enum_value(customer.risk_segment),
        "is_active": customer.is_active,
    }


def _serialize_account(account: Account | None) -> dict[str, Any] | None:
    if account is None:
        return None
    return {
        "id": account.id,
        "account_number": account.account_number,
        "type": _enum_value(account.account_type),
        "status": _enum_value(account.status),
        "currency": _enum_value(account.currency),
        "balance": float(account.balance),
        "formatted_balance": f"{account.balance:,.2f}",
        "customer": _serialize_customer(account.customer),
    }


def _serialize_transaction(transaction: Transaction) -> dict[str, Any]:
    return {
        "id": transaction.id,
        "reference": transaction.transaction_reference,
        "type": _enum_value(transaction.transaction_type),
        "status": _enum_value(transaction.status),
        "amount": float(transaction.amount),
        "formatted_amount": f"{transaction.amount:,.2f}",
        "currency": _enum_value(transaction.currency),
        "occurred_at": _iso_datetime(transaction.occurred_at),
        "description": transaction.description,
        "debit_account": _serialize_account(transaction.debit_account),
        "credit_account": _serialize_account(transaction.credit_account),
    }


def _serialize_assessment_summary(
    assessment: RiskAssessment,
) -> dict[str, Any]:
    return {
        "id": assessment.id,
        "model_version": assessment.model_version,
        "score": assessment.score,
        "risk_level": _enum_value(assessment.risk_level),
        "status": _enum_value(assessment.status),
        "assessed_at": _iso_datetime(assessment.assessed_at),
    }


def _serialize_rule(rule: RiskRule) -> dict[str, Any]:
    return {
        "id": rule.id,
        "code": rule.code,
        "version": rule.version,
        "name": rule.name,
        "category": rule.category,
        "severity": _enum_value(rule.severity),
    }


def _serialize_finding(finding: RiskFinding) -> dict[str, Any]:
    return {
        "id": finding.id,
        "rule_id": finding.rule_id,
        "rule_code": finding.rule_code,
        "rule_name": finding.rule.name if finding.rule else None,
        "score": finding.score,
        "severity": _enum_value(finding.severity),
        "explanation": finding.explanation,
        "evidence": finding.evidence,
        "created_at": _iso_datetime(finding.created_at),
    }


def _serialize_alert(alert: Alert) -> dict[str, Any]:
    transaction = alert.transaction
    customer = _primary_customer(transaction)
    return {
        "alert": {
            "id": alert.id,
            "reference": alert.alert_reference,
            "status": _enum_value(alert.status),
            "priority": _enum_value(alert.priority),
            "score": alert.score,
            "summary": alert.summary,
            "details": alert.details,
            "created_at": _iso_datetime(alert.created_at),
            "acknowledged_at": _iso_datetime(alert.acknowledged_at),
            "closed_at": _iso_datetime(alert.closed_at),
            "assigned_to": alert.assigned_to.full_name if alert.assigned_to else None,
            "assigned_to_user_id": alert.assigned_to_user_id,
        },
        "transaction": _serialize_transaction(transaction),
        "customer": _serialize_customer(customer),
        "assessment": _serialize_assessment_summary(alert.assessment),
        "triggering_rule": _serialize_rule(alert.triggering_rule),
    }


def list_alerts(
    session: Session,
    *,
    q: str | None = None,
    priority: AlertPriority | None = None,
    status: AlertStatus | None = None,
    risk_level: RiskLevel | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = 1,
    per_page: int = DEFAULT_PAGE_SIZE,
) -> dict[str, Any]:
    """Return a filtered, ordered page of alerts with related display data."""

    filters = _normalize_filters(
        q=q,
        priority=priority,
        status=status,
        risk_level=risk_level,
        date_from=date_from,
        date_to=date_to,
    )

    try:
        requested_page = int(page)
    except (TypeError, ValueError):
        requested_page = 1
    requested_page = max(1, requested_page)

    try:
        requested_per_page = int(per_page)
    except (TypeError, ValueError):
        requested_per_page = DEFAULT_PAGE_SIZE
    requested_per_page = min(max(1, requested_per_page), MAX_PAGE_SIZE)

    id_query = _filtered_alert_ids(filters)
    total = session.scalar(select(func.count()).select_from(id_query.subquery())) or 0
    total_pages = max(1, (total + requested_per_page - 1) // requested_per_page)
    current_page = min(requested_page, total_pages)
    offset = (current_page - 1) * requested_per_page

    page_ids = list(
        session.scalars(
            id_query.order_by(Alert.created_at.desc(), Alert.id.desc())
            .offset(offset)
            .limit(requested_per_page)
        ).all()
    )

    alerts_by_id: dict[int, Alert] = {}
    if page_ids:
        alerts = session.scalars(
            select(Alert).where(Alert.id.in_(page_ids)).options(*_list_load_options())
        ).unique()
        alerts_by_id = {alert.id: alert for alert in alerts.all()}

    items = [
        _serialize_alert(alerts_by_id[alert_id])
        for alert_id in page_ids
        if alert_id in alerts_by_id
    ]

    start_index = offset + 1 if items else 0
    end_index = offset + len(items) if items else 0

    return {
        "items": items,
        "filters": filters,
        "pagination": {
            "page": current_page,
            "per_page": requested_per_page,
            "total": total,
            "pages": total_pages,
            "start_index": start_index,
            "end_index": end_index,
            "has_prev": current_page > 1,
            "has_next": current_page < total_pages,
            "prev_page": current_page - 1 if current_page > 1 else None,
            "next_page": current_page + 1 if current_page < total_pages else None,
        },
    }


def get_alert_detail(session: Session, alert_id: int) -> dict[str, Any] | None:
    """Return one alert with its assessment and finding context."""

    alert = session.scalar(
        select(Alert).where(Alert.id == alert_id).options(*_detail_load_options())
    )
    if alert is None:
        return None

    detail = _serialize_alert(alert)
    assessment = alert.assessment
    findings = sorted(
        assessment.findings,
        key=lambda finding: (-finding.score, finding.id),
    )

    detail["assessment"]["explanation"] = assessment.explanation
    detail["assessment"]["findings"] = [
        _serialize_finding(finding) for finding in findings
    ]
    detail["triggering_finding_id"] = alert.finding_id
    detail["triggering_finding"] = (
        _serialize_finding(alert.finding) if alert.finding else None
    )

    return detail


def _workflow_error(
    code: str,
    message: str,
    *,
    alert: Alert | None,
    field: str,
) -> None:
    raise ValidationError(
        ValidationIssue(
            code=code,
            message=message,
            entity_type="alert",
            entity_id=alert.id if alert is not None else None,
            field=field,
        )
    )


def _get_alert_for_update(session: Session, alert_id: int) -> Alert | None:
    return session.scalar(select(Alert).where(Alert.id == alert_id).with_for_update())


def _record_alert_event(
    session: Session,
    alert: Alert,
    actor: User,
    *,
    event_type: str,
    summary: str,
    details: dict[str, Any],
) -> None:
    event = AuditEvent(
        event_type=event_type,
        entity_type="alert",
        entity_id=alert.id,
        actor_user_id=actor.id,
        summary=summary,
        details=details,
        occurred_at=utc_now(),
    )
    validate_audit_event(session, event)
    session.add(event)


def assign_alert(
    session: Session,
    alert_id: int,
    actor: User,
    assignee_id: int | None,
) -> Alert | None:
    """Assign or unassign an open alert and record the change."""

    alert = _get_alert_for_update(session, alert_id)
    if alert is None:
        return None

    if alert.status in (AlertStatus.CLOSED, AlertStatus.DISMISSED):
        _workflow_error(
            "ALERT_ASSIGNMENT_TERMINAL",
            "A closed or dismissed alert cannot be reassigned.",
            alert=alert,
            field="assignee_id",
        )
    if assignee_id == alert.assigned_to_user_id:
        _workflow_error(
            "ALERT_ASSIGNMENT_UNCHANGED",
            "The alert is already assigned as requested.",
            alert=alert,
            field="assignee_id",
        )

    assignee = None
    if assignee_id is not None:
        assignee = session.scalar(
            select(User).where(User.id == assignee_id).with_for_update()
        )
        if (
            assignee is None
            or not assignee.is_active
            or assignee.role not in REVIEW_ROLES
        ):
            _workflow_error(
                "ALERT_ASSIGNEE_INVALID",
                "Choose an active analyst, supervisor, or administrator.",
                alert=alert,
                field="assignee_id",
            )

    previous_assignee_id = alert.assigned_to_user_id
    alert.assigned_to_user_id = assignee.id if assignee is not None else None
    _record_alert_event(
        session,
        alert,
        actor,
        event_type="ALERT_ASSIGNED" if assignee is not None else "ALERT_UNASSIGNED",
        summary=(
            f"Alert assigned to {assignee.full_name}"
            if assignee is not None
            else "Alert unassigned"
        ),
        details={
            "previous_assignee_user_id": previous_assignee_id,
            "assignee_user_id": alert.assigned_to_user_id,
        },
    )
    return alert


def acknowledge_alert(
    session: Session,
    alert_id: int,
    actor: User,
) -> Alert | None:
    """Acknowledge an open alert."""

    alert = _get_alert_for_update(session, alert_id)
    if alert is None:
        return None
    if alert.status != AlertStatus.OPEN:
        _workflow_error(
            "ALERT_TRANSITION_INVALID",
            "Only an open alert can be acknowledged.",
            alert=alert,
            field="status",
        )

    alert.status = AlertStatus.ACKNOWLEDGED
    alert.acknowledged_at = utc_now()
    _record_alert_event(
        session,
        alert,
        actor,
        event_type="ALERT_ACKNOWLEDGED",
        summary="Alert acknowledged",
        details={
            "previous_status": AlertStatus.OPEN.value,
            "status": AlertStatus.ACKNOWLEDGED.value,
        },
    )
    return alert


def _finish_alert(
    session: Session,
    alert_id: int,
    actor: User,
    *,
    status: AlertStatus,
    reason: str,
) -> Alert | None:
    alert = _get_alert_for_update(session, alert_id)
    if alert is None:
        return None

    normalized_reason = reason.strip() if isinstance(reason, str) else ""
    if not normalized_reason:
        _workflow_error(
            "ALERT_REASON_REQUIRED",
            "A reason is required to close or dismiss an alert.",
            alert=alert,
            field="reason",
        )
    if len(normalized_reason) > MAX_WORKFLOW_REASON_LENGTH:
        _workflow_error(
            "ALERT_REASON_TOO_LONG",
            f"The reason must be {MAX_WORKFLOW_REASON_LENGTH} characters or fewer.",
            alert=alert,
            field="reason",
        )

    if alert.status not in (AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED):
        _workflow_error(
            "ALERT_TRANSITION_INVALID",
            "Only an open or acknowledged alert can be closed or dismissed.",
            alert=alert,
            field="status",
        )

    previous_status = alert.status
    alert.status = status
    alert.closed_at = utc_now()
    action = "closed" if status == AlertStatus.CLOSED else "dismissed"
    _record_alert_event(
        session,
        alert,
        actor,
        event_type=f"ALERT_{status.value}",
        summary=f"Alert {action}",
        details={
            "previous_status": previous_status.value,
            "status": status.value,
            "reason": normalized_reason,
        },
    )
    return alert


def close_alert(
    session: Session,
    alert_id: int,
    actor: User,
    reason: str,
) -> Alert | None:
    """Close an open or acknowledged alert with a required reason."""

    return _finish_alert(
        session,
        alert_id,
        actor,
        status=AlertStatus.CLOSED,
        reason=reason,
    )


def dismiss_alert(
    session: Session,
    alert_id: int,
    actor: User,
    reason: str,
) -> Alert | None:
    """Dismiss an open or acknowledged alert with a required reason."""

    return _finish_alert(
        session,
        alert_id,
        actor,
        status=AlertStatus.DISMISSED,
        reason=reason,
    )
