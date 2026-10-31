"""Validation-event recording helpers."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session

from app.models import ValidationEvent
from app.models.enums import ValidationResolutionStatus, ValidationSeverity

from .errors import ValidationIssue


def record_validation_issue(
    session: Session,
    issue: ValidationIssue,
    *,
    transaction_id: int | None = None,
    severity: ValidationSeverity = ValidationSeverity.ERROR,
) -> ValidationEvent:
    """Add a validation event to the current session.

    The caller owns the transaction and must commit the session if the rejected
    input should remain recorded.
    """

    details = dict(issue.details)
    if issue.field is not None:
        details["field"] = issue.field

    event = ValidationEvent(
        event_reference=f"VAL-{uuid4().hex.upper()}",
        validation_code=issue.code[:64],
        severity=severity,
        entity_type=issue.entity_type[:64],
        entity_id=issue.entity_id,
        transaction_id=transaction_id,
        message=issue.message,
        details=details or None,
        resolution_status=ValidationResolutionStatus.OPEN,
    )
    session.add(event)
    return event
