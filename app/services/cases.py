"""Case management queries and transactional workflow services."""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models import (
    Alert,
    AuditEvent,
    Case,
    CaseAlert,
    CaseDecision,
    CaseNote,
    Transaction,
    User,
)
from app.models.base import utc_now
from app.models.enums import (
    AlertStatus,
    CaseDecisionType,
    CaseNoteType,
    CasePriority,
    CaseStatus,
    UserRole,
)
from app.services.validation import (
    ValidationError,
    ValidationIssue,
    validate_audit_event,
    validate_case,
    validate_case_alert,
    validate_case_decision,
    validate_case_note,
)

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
MAX_SEARCH_LENGTH = 100
MAX_ALERTS_PER_CASE = 100
MAX_CASE_REASON_LENGTH = 500
MAX_NOTE_LENGTH = 5000
MAX_RATIONALE_LENGTH = 5000
REVIEW_ROLES = (UserRole.ANALYST, UserRole.SUPERVISOR, UserRole.ADMIN)
MANAGER_ROLES = (UserRole.SUPERVISOR, UserRole.ADMIN)
ACTIVE_ALERT_STATUSES = (AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED)
ALLOWED_CASE_TRANSITIONS = {
    CaseStatus.OPEN: {
        CaseStatus.IN_REVIEW,
        CaseStatus.ESCALATED,
        CaseStatus.CLOSED,
    },
    CaseStatus.IN_REVIEW: {
        CaseStatus.OPEN,
        CaseStatus.ESCALATED,
        CaseStatus.CLOSED,
    },
    CaseStatus.ESCALATED: {
        CaseStatus.IN_REVIEW,
        CaseStatus.CLOSED,
    },
    CaseStatus.CLOSED: set(),
}


def _bounded_int(value: Any, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, 1), maximum)


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _iso_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _raise_workflow_error(
    code: str,
    message: str,
    *,
    field: str | None = None,
    case_id: int | None = None,
) -> None:
    raise ValidationError(
        ValidationIssue(
            code=code,
            message=message,
            entity_type="case",
            entity_id=case_id,
            field=field,
        )
    )


def _is_manager(actor: User) -> bool:
    return actor.role in MANAGER_ROLES


def _require_case_access(case: Case, actor: User, *, case_id: int) -> None:
    if actor.role not in REVIEW_ROLES:
        _raise_workflow_error(
            "CASE_PERMISSION_DENIED",
            "You do not have permission to manage cases.",
            case_id=case_id,
        )
    if not _is_manager(actor) and case.assigned_to_user_id != actor.id:
        _raise_workflow_error(
            "CASE_ASSIGNMENT_REQUIRED",
            "Claim this unassigned case or work on a case assigned to you.",
            case_id=case_id,
        )
    if case.status == CaseStatus.CLOSED:
        _raise_workflow_error(
            "CASE_CLOSED",
            "A closed case cannot be changed.",
            case_id=case_id,
        )


def _get_case_for_update(session: Session, case_id: int) -> Case | None:
    return session.scalar(select(Case).where(Case.id == case_id).with_for_update())


def _record_case_event(
    session: Session,
    case: Case,
    actor: User,
    *,
    event_type: str,
    summary: str,
    details: dict[str, Any],
) -> None:
    event = AuditEvent(
        event_type=event_type,
        entity_type="case",
        entity_id=case.id,
        actor_user_id=actor.id,
        summary=summary,
        details=details,
        occurred_at=utc_now(),
    )
    validate_audit_event(session, event, record_event=False)
    session.add(event)


def _active_alert_link_query(alert_id: int):
    return select(CaseAlert).where(
        CaseAlert.alert_id == alert_id,
        CaseAlert.unlinked_at.is_(None),
    )


def list_eligible_alerts(
    session: Session,
    *,
    q: str | None = None,
    alert_id: int | None = None,
    limit: int = MAX_ALERTS_PER_CASE,
) -> list[dict[str, Any]]:
    """Return open, unacknowledged-or-acknowledged alerts not already linked."""

    term = (q or "").strip()[:MAX_SEARCH_LENGTH]
    query = (
        select(Alert)
        .join(Alert.transaction)
        .where(
            Alert.status.in_(ACTIVE_ALERT_STATUSES),
            ~_active_alert_link_query(Alert.id).exists(),
        )
        .options(joinedload(Alert.transaction))
        .order_by(Alert.created_at.desc(), Alert.id.desc())
        .limit(_bounded_int(limit, MAX_ALERTS_PER_CASE, MAX_ALERTS_PER_CASE))
    )
    if alert_id is not None:
        query = query.where(Alert.id == alert_id)
    if term:
        pattern = f"%{term}%"
        query = query.where(
            or_(
                Alert.alert_reference.ilike(pattern),
                Alert.summary.ilike(pattern),
                Transaction.transaction_reference.ilike(pattern),
            )
        )
    return [
        {
            "id": alert.id,
            "reference": alert.alert_reference,
            "status": _enum_value(alert.status),
            "priority": _enum_value(alert.priority),
            "summary": alert.summary,
            "transaction_id": alert.transaction_id,
            "transaction_reference": alert.transaction.transaction_reference,
            "created_at": _iso_datetime(alert.created_at),
        }
        for alert in session.scalars(query).unique().all()
    ]


def get_active_case_for_alert(
    session: Session,
    alert_id: int,
) -> dict[str, Any] | None:
    """Return the active case link for an alert, if it has one."""

    row = session.execute(
        select(Case.id, Case.case_reference)
        .join(CaseAlert, CaseAlert.case_id == Case.id)
        .where(CaseAlert.alert_id == alert_id, CaseAlert.unlinked_at.is_(None))
    ).first()
    if row is None:
        return None
    return {"id": row.id, "reference": row.case_reference}


def list_cases(
    session: Session,
    *,
    q: str | None = None,
    status: CaseStatus | None = None,
    priority: CasePriority | None = None,
    assigned_to_user_id: int | None = None,
    unassigned_only: bool = False,
    visible_to_user_id: int | None = None,
    page: Any = 1,
    per_page: Any = DEFAULT_PAGE_SIZE,
) -> dict[str, Any]:
    """Return a filtered, stably ordered page of cases."""

    term = (q or "").strip()[:MAX_SEARCH_LENGTH]
    current_page = _bounded_int(page, 1, 1_000_000)
    page_size = _bounded_int(per_page, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE)
    conditions = []
    if status is not None:
        conditions.append(Case.status == status)
    if priority is not None:
        conditions.append(Case.priority == priority)
    if assigned_to_user_id is not None:
        conditions.append(Case.assigned_to_user_id == assigned_to_user_id)
    if unassigned_only:
        conditions.append(Case.assigned_to_user_id.is_(None))
    if visible_to_user_id is not None:
        conditions.append(
            or_(
                Case.assigned_to_user_id == visible_to_user_id,
                Case.assigned_to_user_id.is_(None),
            )
        )
    if term:
        pattern = f"%{term}%"
        conditions.append(
            or_(
                Case.case_reference.ilike(pattern),
                Case.title.ilike(pattern),
                Case.description.ilike(pattern),
            )
        )

    total = session.scalar(select(func.count(Case.id)).where(*conditions)) or 0
    pages = max(1, (total + page_size - 1) // page_size)
    current_page = min(current_page, pages)
    rows = session.execute(
        select(
            Case,
            func.count(CaseAlert.id).label("active_alert_count"),
        )
        .outerjoin(
            CaseAlert,
            and_(
                CaseAlert.case_id == Case.id,
                CaseAlert.unlinked_at.is_(None),
            ),
        )
        .where(*conditions)
        .options(joinedload(Case.assigned_to), joinedload(Case.opened_by))
        .group_by(Case.id)
        .order_by(Case.opened_at.desc(), Case.id.desc())
        .offset((current_page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [
            {
                "id": case.id,
                "reference": case.case_reference,
                "title": case.title,
                "status": _enum_value(case.status),
                "priority": _enum_value(case.priority),
                "assigned_to": (
                    case.assigned_to.full_name if case.assigned_to else None
                ),
                "assigned_to_user_id": case.assigned_to_user_id,
                "opened_by": case.opened_by.full_name,
                "opened_at": _iso_datetime(case.opened_at),
                "active_alert_count": active_alert_count,
            }
            for case, active_alert_count in rows
        ],
        "filters": {
            "q": term,
            "status": _enum_value(status) if status is not None else "",
            "priority": _enum_value(priority) if priority is not None else "",
            "assigned_to_user_id": assigned_to_user_id,
        },
        "pagination": {
            "page": current_page,
            "per_page": page_size,
            "total": total,
            "pages": pages,
            "has_prev": current_page > 1,
            "has_next": current_page < pages,
            "prev_page": current_page - 1 if current_page > 1 else None,
            "next_page": current_page + 1 if current_page < pages else None,
        },
    }


def get_case_detail(session: Session, case_id: int) -> dict[str, Any] | None:
    """Return a case with its recorded links, notes, decisions, and audit history."""

    case = session.scalar(
        select(Case)
        .where(Case.id == case_id)
        .options(
            joinedload(Case.assigned_to),
            joinedload(Case.opened_by),
            joinedload(Case.closed_by),
            selectinload(Case.case_alerts)
            .joinedload(CaseAlert.alert)
            .joinedload(Alert.transaction),
            selectinload(Case.case_alerts).joinedload(CaseAlert.linked_by),
            selectinload(Case.case_alerts).joinedload(CaseAlert.unlinked_by),
            selectinload(Case.notes).joinedload(CaseNote.author),
            selectinload(Case.decisions).joinedload(CaseDecision.decided_by),
            selectinload(Case.decisions).joinedload(CaseDecision.triggering_alert),
        )
    )
    if case is None:
        return None
    audit_events = session.scalars(
        select(AuditEvent)
        .where(AuditEvent.entity_type == "case", AuditEvent.entity_id == case.id)
        .order_by(AuditEvent.occurred_at, AuditEvent.id)
    ).all()
    links = sorted(case.case_alerts, key=lambda link: (link.linked_at, link.id))
    notes = sorted(case.notes, key=lambda note: (note.noted_at, note.id))
    decisions = sorted(
        case.decisions,
        key=lambda decision: (decision.decided_at, decision.id),
    )
    return {
        "case": {
            "id": case.id,
            "reference": case.case_reference,
            "title": case.title,
            "description": case.description,
            "status": _enum_value(case.status),
            "priority": _enum_value(case.priority),
            "assigned_to": case.assigned_to.full_name if case.assigned_to else None,
            "assigned_to_user_id": case.assigned_to_user_id,
            "opened_by": case.opened_by.full_name,
            "opened_at": _iso_datetime(case.opened_at),
            "closed_by": case.closed_by.full_name if case.closed_by else None,
            "closed_at": _iso_datetime(case.closed_at),
            "is_closed": case.status == CaseStatus.CLOSED,
        },
        "links": [
            {
                "id": link.id,
                "alert_id": link.alert_id,
                "alert_reference": link.alert.alert_reference,
                "alert_summary": link.alert.summary,
                "alert_status": _enum_value(link.alert.status),
                "transaction_id": link.alert.transaction_id,
                "transaction_reference": (link.alert.transaction.transaction_reference),
                "linked_by": link.linked_by.full_name,
                "linked_at": _iso_datetime(link.linked_at),
                "unlinked_by": (
                    link.unlinked_by.full_name if link.unlinked_by else None
                ),
                "unlinked_at": _iso_datetime(link.unlinked_at),
                "unlink_reason": link.unlink_reason,
                "active": link.unlinked_at is None,
            }
            for link in links
        ],
        "notes": [
            {
                "id": note.id,
                "type": _enum_value(note.note_type),
                "body": note.body,
                "author": note.author.full_name,
                "noted_at": _iso_datetime(note.noted_at),
            }
            for note in notes
        ],
        "decisions": [
            {
                "id": decision.id,
                "type": _enum_value(decision.decision),
                "rationale": decision.rationale,
                "decided_by": decision.decided_by.full_name,
                "decided_at": _iso_datetime(decision.decided_at),
                "alert_id": decision.triggering_alert_id,
                "alert_reference": decision.triggering_alert.alert_reference,
            }
            for decision in decisions
        ],
        "audit_events": [
            {
                "event_type": event.event_type,
                "summary": event.summary,
                "details": event.details,
                "actor": event.actor.full_name if event.actor else "System",
                "occurred_at": _iso_datetime(event.occurred_at),
            }
            for event in audit_events
        ],
    }


def create_case(
    session: Session,
    actor: User,
    *,
    title: str,
    description: str | None,
    priority: CasePriority | str,
    alert_ids: list[int],
) -> Case:
    """Create a case assigned to its creator and link eligible alerts."""

    if actor.role not in REVIEW_ROLES:
        _raise_workflow_error(
            "CASE_PERMISSION_DENIED",
            "You do not have permission to create cases.",
        )
    normalized_title = title.strip() if isinstance(title, str) else ""
    if not normalized_title or len(normalized_title) > 200:
        _raise_workflow_error(
            "CASE_TITLE_INVALID",
            "A case title of 1 to 200 characters is required.",
            field="title",
        )
    normalized_description = (
        description.strip()
        if isinstance(description, str) and description.strip()
        else None
    )
    try:
        normalized_priority = CasePriority(priority)
    except (TypeError, ValueError):
        _raise_workflow_error(
            "CASE_PRIORITY_INVALID",
            "Choose a valid case priority.",
            field="priority",
        )
    if not alert_ids or len(alert_ids) > MAX_ALERTS_PER_CASE:
        _raise_workflow_error(
            "CASE_ALERTS_REQUIRED",
            f"Select between 1 and {MAX_ALERTS_PER_CASE} alerts.",
            field="alert_ids",
        )
    if len(set(alert_ids)) != len(alert_ids):
        _raise_workflow_error(
            "CASE_ALERT_DUPLICATE",
            "An alert may be selected only once.",
            field="alert_ids",
        )

    alerts = list(
        session.scalars(
            select(Alert)
            .where(Alert.id.in_(alert_ids))
            .order_by(Alert.id)
            .with_for_update()
        ).all()
    )
    if len(alerts) != len(alert_ids):
        _raise_workflow_error(
            "CASE_ALERT_NOT_FOUND",
            "One or more selected alerts do not exist.",
            field="alert_ids",
        )
    for alert in alerts:
        if alert.status not in ACTIVE_ALERT_STATUSES:
            _raise_workflow_error(
                "CASE_ALERT_STATUS_INVALID",
                "Only open or acknowledged alerts can be linked.",
                field="alert_ids",
            )
        if session.scalar(_active_alert_link_query(alert.id).limit(1)) is not None:
            _raise_workflow_error(
                "CASE_ALERT_ALREADY_LINKED",
                f"Alert {alert.alert_reference} is already linked to an active case.",
                field="alert_ids",
            )

    now = utc_now()
    case = Case(
        case_reference=f"CASE-{secrets.token_hex(6).upper()}",
        title=normalized_title,
        description=normalized_description,
        status=CaseStatus.OPEN,
        priority=normalized_priority,
        assigned_to_user_id=actor.id,
        opened_by_user_id=actor.id,
        opened_at=now,
    )
    session.add(case)
    session.flush()
    validate_case(session, case, record_event=False)
    for alert in alerts:
        link = CaseAlert(
            case_id=case.id,
            alert_id=alert.id,
            linked_by_user_id=actor.id,
            linked_at=now,
        )
        validate_case_alert(session, link, record_event=False)
        session.add(link)
    _record_case_event(
        session,
        case,
        actor,
        event_type="CASE_CREATED",
        summary=f"Case created with {len(alerts)} linked alert(s)",
        details={
            "alert_ids": [alert.id for alert in alerts],
            "priority": normalized_priority.value,
        },
    )
    return case


def claim_case(session: Session, case_id: int, actor: User) -> Case | None:
    """Claim an unassigned open case for an analyst."""

    if actor.role != UserRole.ANALYST:
        _raise_workflow_error("CASE_PERMISSION_DENIED", "Case access denied.")
    case = _get_case_for_update(session, case_id)
    if case is None:
        return None
    if case.status == CaseStatus.CLOSED:
        _raise_workflow_error("CASE_CLOSED", "A closed case cannot be claimed.")
    if case.assigned_to_user_id is not None:
        _raise_workflow_error(
            "CASE_ALREADY_ASSIGNED",
            "Only an unassigned case can be claimed.",
            case_id=case.id,
        )
    case.assigned_to_user_id = actor.id
    _record_case_event(
        session,
        case,
        actor,
        event_type="CASE_CLAIMED",
        summary="Case claimed by assigned reviewer",
        details={"assignee_user_id": actor.id},
    )
    return case


def assign_case(
    session: Session,
    case_id: int,
    actor: User,
    assignee_id: int | None,
) -> Case | None:
    """Assign or unassign a case; restricted to supervisors and admins."""

    case = _get_case_for_update(session, case_id)
    if case is None:
        return None
    if not _is_manager(actor):
        _raise_workflow_error(
            "CASE_MANAGER_REQUIRED",
            "Only supervisors and admins can manage case assignments.",
            case_id=case.id,
        )
    if case.status == CaseStatus.CLOSED:
        _raise_workflow_error("CASE_CLOSED", "A closed case cannot be changed.")
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
            _raise_workflow_error(
                "CASE_ASSIGNEE_INVALID",
                "Choose an active analyst, supervisor, or administrator.",
                field="assignee_id",
                case_id=case.id,
            )
    previous_id = case.assigned_to_user_id
    new_id = assignee.id if assignee is not None else None
    if previous_id == new_id:
        _raise_workflow_error(
            "CASE_ASSIGNMENT_UNCHANGED",
            "The case is already assigned as requested.",
            case_id=case.id,
        )
    case.assigned_to_user_id = new_id
    _record_case_event(
        session,
        case,
        actor,
        event_type="CASE_ASSIGNED" if assignee else "CASE_UNASSIGNED",
        summary=(
            f"Case assigned to {assignee.full_name}" if assignee else "Case unassigned"
        ),
        details={
            "previous_assignee_user_id": previous_id,
            "assignee_user_id": new_id,
        },
    )
    return case


def set_case_priority(
    session: Session,
    case_id: int,
    actor: User,
    priority: CasePriority | str,
) -> Case | None:
    """Change case priority; restricted to supervisors and admins."""

    case = _get_case_for_update(session, case_id)
    if case is None:
        return None
    if not _is_manager(actor):
        _raise_workflow_error(
            "CASE_MANAGER_REQUIRED",
            "Only supervisors and admins can change case priority.",
            case_id=case.id,
        )
    if case.status == CaseStatus.CLOSED:
        _raise_workflow_error("CASE_CLOSED", "A closed case cannot be changed.")
    try:
        normalized = CasePriority(priority)
    except (TypeError, ValueError):
        _raise_workflow_error(
            "CASE_PRIORITY_INVALID",
            "Choose a valid case priority.",
            field="priority",
            case_id=case.id,
        )
    previous = case.priority
    if previous == normalized:
        _raise_workflow_error(
            "CASE_PRIORITY_UNCHANGED",
            "The case already has that priority.",
            case_id=case.id,
        )
    case.priority = normalized
    _record_case_event(
        session,
        case,
        actor,
        event_type="CASE_PRIORITY_CHANGED",
        summary=f"Case priority changed to {normalized.value}",
        details={"previous_priority": previous.value, "priority": normalized.value},
    )
    return case


def transition_case(
    session: Session,
    case_id: int,
    actor: User,
    status: CaseStatus | str,
    reason: str = "",
) -> Case | None:
    """Transition a case according to the approved state machine."""

    case = _get_case_for_update(session, case_id)
    if case is None:
        return None
    target = _parse_case_status(status, case.id)
    _require_case_access(case, actor, case_id=case.id)
    if target not in ALLOWED_CASE_TRANSITIONS[case.status]:
        _raise_workflow_error(
            "CASE_TRANSITION_INVALID",
            f"Cannot move a {case.status.value} case to {target.value}.",
            field="status",
            case_id=case.id,
        )
    if target in (CaseStatus.ESCALATED, CaseStatus.CLOSED) and not _is_manager(actor):
        _raise_workflow_error(
            "CASE_MANAGER_REQUIRED",
            "Only supervisors and admins can escalate or close a case.",
            case_id=case.id,
        )
    normalized_reason = reason.strip() if isinstance(reason, str) else ""
    if target in (CaseStatus.ESCALATED, CaseStatus.CLOSED):
        if not normalized_reason:
            _raise_workflow_error(
                "CASE_REASON_REQUIRED",
                "A reason is required to escalate or close a case.",
                field="reason",
                case_id=case.id,
            )
        if len(normalized_reason) > MAX_CASE_REASON_LENGTH:
            _raise_workflow_error(
                "CASE_REASON_TOO_LONG",
                f"The reason must be {MAX_CASE_REASON_LENGTH} characters or fewer.",
                field="reason",
                case_id=case.id,
            )
    previous = case.status
    case.status = target
    if target == CaseStatus.CLOSED:
        case.closed_at = utc_now()
        case.closed_by_user_id = actor.id
    else:
        case.closed_at = None
        case.closed_by_user_id = None
    validate_case(session, case, record_event=False)
    details: dict[str, Any] = {
        "previous_status": previous.value,
        "status": target.value,
    }
    if normalized_reason:
        details["reason"] = normalized_reason
    _record_case_event(
        session,
        case,
        actor,
        event_type=f"CASE_STATUS_{target.value}",
        summary=f"Case moved from {previous.value} to {target.value}",
        details=details,
    )
    return case


def _parse_case_status(status: CaseStatus | str, case_id: int) -> CaseStatus:
    try:
        return CaseStatus(status)
    except (TypeError, ValueError):
        _raise_workflow_error(
            "CASE_STATUS_INVALID",
            "Choose a valid case status.",
            field="status",
            case_id=case_id,
        )


def link_alert_to_case(
    session: Session,
    case_id: int,
    alert_id: int,
    actor: User,
) -> CaseAlert | None:
    """Link an eligible alert to a nonclosed case."""

    case = _get_case_for_update(session, case_id)
    if case is None:
        return None
    _require_case_access(case, actor, case_id=case.id)
    alert = session.scalar(select(Alert).where(Alert.id == alert_id).with_for_update())
    if alert is None:
        _raise_workflow_error(
            "CASE_ALERT_NOT_FOUND",
            "The selected alert does not exist.",
            field="alert_id",
            case_id=case.id,
        )
    if alert.status not in ACTIVE_ALERT_STATUSES:
        _raise_workflow_error(
            "CASE_ALERT_STATUS_INVALID",
            "Only open or acknowledged alerts can be linked.",
            field="alert_id",
            case_id=case.id,
        )
    if session.scalar(_active_alert_link_query(alert.id).limit(1)) is not None:
        _raise_workflow_error(
            "CASE_ALERT_ALREADY_LINKED",
            "This alert is already linked to an active case.",
            field="alert_id",
            case_id=case.id,
        )
    link = CaseAlert(
        case_id=case.id,
        alert_id=alert.id,
        linked_by_user_id=actor.id,
        linked_at=utc_now(),
    )
    validate_case_alert(session, link, record_event=False)
    session.add(link)
    _record_case_event(
        session,
        case,
        actor,
        event_type="CASE_ALERT_LINKED",
        summary=f"Alert {alert.alert_reference} linked to case",
        details={"alert_id": alert.id, "alert_reference": alert.alert_reference},
    )
    return link


def unlink_alert_from_case(
    session: Session,
    case_id: int,
    link_id: int,
    actor: User,
    reason: str,
) -> CaseAlert | None:
    """Soft-unlink an alert while preserving the original case link."""

    case = _get_case_for_update(session, case_id)
    if case is None:
        return None
    _require_case_access(case, actor, case_id=case.id)
    normalized_reason = reason.strip() if isinstance(reason, str) else ""
    if not normalized_reason or len(normalized_reason) > MAX_CASE_REASON_LENGTH:
        _raise_workflow_error(
            "CASE_UNLINK_REASON_INVALID",
            f"A reason of 1 to {MAX_CASE_REASON_LENGTH} characters is required.",
            field="reason",
            case_id=case.id,
        )
    link = session.scalar(
        select(CaseAlert)
        .where(
            CaseAlert.id == link_id,
            CaseAlert.case_id == case.id,
            CaseAlert.unlinked_at.is_(None),
        )
        .with_for_update()
    )
    if link is None:
        return None
    active_count = (
        session.scalar(
            select(func.count(CaseAlert.id)).where(
                CaseAlert.case_id == case.id,
                CaseAlert.unlinked_at.is_(None),
            )
        )
        or 0
    )
    if active_count <= 1:
        _raise_workflow_error(
            "CASE_REQUIRES_ACTIVE_ALERT",
            "A case must retain at least one active alert.",
            case_id=case.id,
        )
    link.unlinked_at = utc_now()
    link.unlinked_by_user_id = actor.id
    link.unlink_reason = normalized_reason
    validate_case_alert(session, link, record_event=False)
    _record_case_event(
        session,
        case,
        actor,
        event_type="CASE_ALERT_UNLINKED",
        summary=f"Alert {link.alert.alert_reference} unlinked from case",
        details={
            "alert_id": link.alert_id,
            "link_id": link.id,
            "reason": normalized_reason,
        },
    )
    return link


def add_case_note(
    session: Session,
    case_id: int,
    actor: User,
    *,
    body: str,
    note_type: CaseNoteType | str = CaseNoteType.INVESTIGATION,
) -> CaseNote | None:
    """Append a case note and corresponding audit event."""

    case = _get_case_for_update(session, case_id)
    if case is None:
        return None
    _require_case_access(case, actor, case_id=case.id)
    normalized_body = body.strip() if isinstance(body, str) else ""
    if not normalized_body or len(normalized_body) > MAX_NOTE_LENGTH:
        _raise_workflow_error(
            "CASE_NOTE_INVALID",
            f"A note of 1 to {MAX_NOTE_LENGTH} characters is required.",
            field="body",
            case_id=case.id,
        )
    try:
        normalized_type = CaseNoteType(note_type)
    except (TypeError, ValueError):
        _raise_workflow_error(
            "CASE_NOTE_TYPE_INVALID",
            "Choose a valid note type.",
            field="note_type",
            case_id=case.id,
        )
    note = CaseNote(
        case_id=case.id,
        author_user_id=actor.id,
        note_type=normalized_type,
        body=normalized_body,
        noted_at=utc_now(),
    )
    validate_case_note(session, note, record_event=False)
    session.add(note)
    _record_case_event(
        session,
        case,
        actor,
        event_type="CASE_NOTE_ADDED",
        summary=f"{normalized_type.value.title()} note added",
        details={"note_type": normalized_type.value},
    )
    return note


def add_case_decision(
    session: Session,
    case_id: int,
    actor: User,
    *,
    alert_id: int,
    decision: CaseDecisionType | str,
    rationale: str,
) -> CaseDecision | None:
    """Append a decision tied to an actively linked alert."""

    case = _get_case_for_update(session, case_id)
    if case is None:
        return None
    _require_case_access(case, actor, case_id=case.id)
    normalized_rationale = rationale.strip() if isinstance(rationale, str) else ""
    if not normalized_rationale or len(normalized_rationale) > MAX_RATIONALE_LENGTH:
        _raise_workflow_error(
            "CASE_RATIONALE_INVALID",
            f"A rationale of 1 to {MAX_RATIONALE_LENGTH} characters is required.",
            field="rationale",
            case_id=case.id,
        )
    try:
        normalized_decision = CaseDecisionType(decision)
    except (TypeError, ValueError):
        _raise_workflow_error(
            "CASE_DECISION_INVALID",
            "Choose a valid case decision.",
            field="decision",
            case_id=case.id,
        )
    decision_record = CaseDecision(
        case_id=case.id,
        decided_by_user_id=actor.id,
        decision=normalized_decision,
        rationale=normalized_rationale,
        decided_at=utc_now(),
        triggering_alert_id=alert_id,
    )
    validate_case_decision(session, decision_record, record_event=False)
    session.add(decision_record)
    _record_case_event(
        session,
        case,
        actor,
        event_type="CASE_DECISION_RECORDED",
        summary=f"Decision recorded: {normalized_decision.value}",
        details={
            "decision": normalized_decision.value,
            "alert_id": alert_id,
        },
    )
    return decision_record
