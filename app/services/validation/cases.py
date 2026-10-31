"""Case, case-link, note, and decision validators."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Alert, Case, CaseAlert, CaseDecision, CaseNote, User
from app.models.enums import (
    CaseDecisionType,
    CaseNoteType,
    CasePriority,
    CaseStatus,
)

from .base import (
    require,
    require_enum,
    require_non_blank,
    require_reference,
    require_timestamp,
    require_timestamp_order,
)


def validate_case(
    session: Session,
    case: Case,
    *,
    record_event: bool = True,
) -> Case:
    """Validate case ownership, status, and timestamps."""

    entity_type = "case"
    entity_id = case.id
    require_non_blank(
        case.case_reference,
        session=session,
        field="case_reference",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_non_blank(
        case.title,
        session=session,
        field="title",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    status = require_enum(
        case.status,
        CaseStatus,
        session=session,
        field="status",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_enum(
        case.priority,
        CasePriority,
        session=session,
        field="priority",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_reference(
        session,
        User,
        case.opened_by_user_id,
        field="opened_by_user_id",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_reference(
        session,
        User,
        case.assigned_to_user_id,
        field="assigned_to_user_id",
        entity_type=entity_type,
        entity_id=entity_id,
        required=False,
        record_event=record_event,
    )
    require_reference(
        session,
        User,
        case.closed_by_user_id,
        field="closed_by_user_id",
        entity_type=entity_type,
        entity_id=entity_id,
        required=False,
        record_event=record_event,
    )
    require_timestamp(
        case.opened_at,
        session=session,
        field="opened_at",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_timestamp_order(
        case.opened_at,
        case.closed_at,
        session=session,
        earlier_field="opened_at",
        later_field="closed_at",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require(
        (status == CaseStatus.CLOSED and case.closed_at is not None)
        or (status != CaseStatus.CLOSED and case.closed_at is None),
        session=session,
        code="CLOSED_TIMESTAMP_MISMATCH",
        message="closed_at must be set only when status is CLOSED",
        entity_type=entity_type,
        entity_id=entity_id,
        field="closed_at",
        details={
            "status": status.value,
            "closed_at": (
                case.closed_at.isoformat() if case.closed_at is not None else None
            ),
        },
        record_event=record_event,
    )
    return case


def validate_case_alert(
    session: Session,
    link: CaseAlert,
    *,
    record_event: bool = True,
) -> CaseAlert:
    """Validate a case-alert link and its unlink history."""

    entity_type = "case_alert"
    entity_id = link.id
    case = require_reference(
        session,
        Case,
        link.case_id,
        field="case_id",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    alert = require_reference(
        session,
        Alert,
        link.alert_id,
        field="alert_id",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_reference(
        session,
        User,
        link.linked_by_user_id,
        field="linked_by_user_id",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_timestamp(
        link.linked_at,
        session=session,
        field="linked_at",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_timestamp_order(
        alert.created_at,
        link.linked_at,
        session=session,
        earlier_field="alert.created_at",
        later_field="linked_at",
        entity_type=entity_type,
        entity_id=entity_id,
        code="CASE_ALERT_BEFORE_ALERT_CREATED",
        record_event=record_event,
    )
    require_timestamp_order(
        case.opened_at,
        link.linked_at,
        session=session,
        earlier_field="case.opened_at",
        later_field="linked_at",
        entity_type=entity_type,
        entity_id=entity_id,
        code="CASE_ALERT_BEFORE_CASE_OPENED",
        record_event=record_event,
    )
    if link.unlinked_at is None:
        require(
            link.unlinked_by_user_id is None and link.unlink_reason is None,
            session=session,
            code="CASE_ALERT_UNLINK_MISMATCH",
            message="An active link cannot contain unlink metadata",
            entity_type=entity_type,
            entity_id=entity_id,
            field="unlinked_at",
            record_event=record_event,
        )
        return link

    require_timestamp(
        link.unlinked_at,
        session=session,
        field="unlinked_at",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require(
        link.unlinked_by_user_id is not None,
        session=session,
        code="CASE_ALERT_UNLINK_MISSING_ACTOR",
        message="An unlinked case alert requires unlinked_by_user_id",
        entity_type=entity_type,
        entity_id=entity_id,
        field="unlinked_by_user_id",
        record_event=record_event,
    )
    require_reference(
        session,
        User,
        link.unlinked_by_user_id,
        field="unlinked_by_user_id",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_non_blank(
        link.unlink_reason,
        session=session,
        field="unlink_reason",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_timestamp_order(
        link.linked_at,
        link.unlinked_at,
        session=session,
        earlier_field="linked_at",
        later_field="unlinked_at",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    return link


def validate_case_note(
    session: Session,
    note: CaseNote,
    *,
    record_event: bool = True,
) -> CaseNote:
    """Validate a case note's references, type, body, and timestamp."""

    entity_type = "case_note"
    entity_id = note.id
    case = require_reference(
        session,
        Case,
        note.case_id,
        field="case_id",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_reference(
        session,
        User,
        note.author_user_id,
        field="author_user_id",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_enum(
        note.note_type,
        CaseNoteType,
        session=session,
        field="note_type",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_non_blank(
        note.body,
        session=session,
        field="body",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_timestamp(
        note.noted_at,
        session=session,
        field="noted_at",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_timestamp_order(
        case.opened_at,
        note.noted_at,
        session=session,
        earlier_field="case.opened_at",
        later_field="noted_at",
        entity_type=entity_type,
        entity_id=entity_id,
        code="CASE_NOTE_BEFORE_CASE_OPENED",
        record_event=record_event,
    )
    return note


def validate_case_decision(
    session: Session,
    decision: CaseDecision,
    *,
    record_event: bool = True,
) -> CaseDecision:
    """Validate a decision's references and alert-relative ordering."""

    entity_type = "case_decision"
    entity_id = decision.id
    case = require_reference(
        session,
        Case,
        decision.case_id,
        field="case_id",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_reference(
        session,
        User,
        decision.decided_by_user_id,
        field="decided_by_user_id",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require(
        decision.triggering_alert_id is not None,
        session=session,
        code="CASE_DECISION_MISSING_ALERT",
        message="A case decision requires a triggering alert",
        entity_type=entity_type,
        entity_id=entity_id,
        field="triggering_alert_id",
        record_event=record_event,
    )
    alert = require_reference(
        session,
        Alert,
        decision.triggering_alert_id,
        field="triggering_alert_id",
        entity_type=entity_type,
        entity_id=entity_id,
        code="CASE_DECISION_ALERT_NOT_FOUND",
        record_event=record_event,
    )
    require_enum(
        decision.decision,
        CaseDecisionType,
        session=session,
        field="decision",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_non_blank(
        decision.rationale,
        session=session,
        field="rationale",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_timestamp(
        decision.decided_at,
        session=session,
        field="decided_at",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_timestamp_order(
        alert.created_at,
        decision.decided_at,
        session=session,
        earlier_field="alert.created_at",
        later_field="decided_at",
        entity_type=entity_type,
        entity_id=entity_id,
        code="CASE_DECISION_BEFORE_ALERT",
        record_event=record_event,
    )
    require_timestamp_order(
        case.opened_at,
        decision.decided_at,
        session=session,
        earlier_field="case.opened_at",
        later_field="decided_at",
        entity_type=entity_type,
        entity_id=entity_id,
        code="CASE_DECISION_BEFORE_CASE_OPENED",
        record_event=record_event,
    )

    active_link = session.scalar(
        select(CaseAlert).where(
            CaseAlert.case_id == case.id,
            CaseAlert.alert_id == alert.id,
            CaseAlert.unlinked_at.is_(None),
        )
    )
    require(
        active_link is not None,
        session=session,
        code="CASE_DECISION_ALERT_NOT_LINKED",
        message="The triggering alert must be actively linked to the case",
        entity_type=entity_type,
        entity_id=entity_id,
        field="triggering_alert_id",
        details={"case_id": case.id, "alert_id": alert.id},
        record_event=record_event,
    )
    earliest_linked_at = session.scalar(
        select(func.min(CaseAlert.linked_at)).where(
            CaseAlert.case_id == case.id,
            CaseAlert.unlinked_at.is_(None),
        )
    )
    require_timestamp_order(
        earliest_linked_at,
        decision.decided_at,
        session=session,
        earlier_field="earliest_case_alert.linked_at",
        later_field="decided_at",
        entity_type=entity_type,
        entity_id=entity_id,
        code="CASE_DECISION_BEFORE_ALERT_LINK",
        record_event=record_event,
    )
    return decision
