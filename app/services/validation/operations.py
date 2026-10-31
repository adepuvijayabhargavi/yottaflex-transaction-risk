"""Dataset-run, audit-event, and validation-event validators."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import AuditEvent, DatasetRun, Transaction, User, ValidationEvent
from app.models.enums import (
    DatasetRunStatus,
    ValidationResolutionStatus,
    ValidationSeverity,
)

from .base import (
    require,
    require_enum,
    require_non_blank,
    require_reference,
    require_timestamp,
    require_timestamp_order,
)


def validate_dataset_run(
    session: Session,
    run: DatasetRun,
    *,
    record_event: bool = True,
) -> DatasetRun:
    """Validate a reproducible dataset-run record and its timestamps."""

    entity_type = "dataset_run"
    entity_id = run.id
    require_non_blank(
        run.run_reference,
        session=session,
        field="run_reference",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_non_blank(
        run.profile_name,
        session=session,
        field="profile_name",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require(
        isinstance(run.seed, int) and not isinstance(run.seed, bool),
        session=session,
        code="INVALID_SEED",
        message="seed must be an integer",
        entity_type=entity_type,
        entity_id=entity_id,
        field="seed",
        record_event=record_event,
    )
    require_enum(
        run.status,
        DatasetRunStatus,
        session=session,
        field="status",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_timestamp(
        run.reference_datetime_utc,
        session=session,
        field="reference_datetime_utc",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_timestamp(
        run.started_at,
        session=session,
        field="started_at",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_timestamp_order(
        run.started_at,
        run.completed_at,
        session=session,
        earlier_field="started_at",
        later_field="completed_at",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require(
        isinstance(run.record_counts, dict),
        session=session,
        code="INVALID_RECORD_COUNTS",
        message="record_counts must be a JSON object",
        entity_type=entity_type,
        entity_id=entity_id,
        field="record_counts",
        record_event=record_event,
    )
    require(
        isinstance(run.checksums, dict),
        session=session,
        code="INVALID_CHECKSUMS",
        message="checksums must be a JSON object",
        entity_type=entity_type,
        entity_id=entity_id,
        field="checksums",
        record_event=record_event,
    )
    return run


def validate_validation_event(
    session: Session,
    event: ValidationEvent,
    *,
    record_event: bool = True,
) -> ValidationEvent:
    """Validate a validation event's fields and resolution state."""

    entity_type = "validation_event"
    entity_id = event.id
    require_non_blank(
        event.event_reference,
        session=session,
        field="event_reference",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_non_blank(
        event.validation_code,
        session=session,
        field="validation_code",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_enum(
        event.severity,
        ValidationSeverity,
        session=session,
        field="severity",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_non_blank(
        event.entity_type,
        session=session,
        field="entity_type",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_non_blank(
        event.message,
        session=session,
        field="message",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_reference(
        session,
        Transaction,
        event.transaction_id,
        field="transaction_id",
        entity_type=entity_type,
        entity_id=entity_id,
        required=False,
        record_event=record_event,
    )
    resolution = require_enum(
        event.resolution_status,
        ValidationResolutionStatus,
        session=session,
        field="resolution_status",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_reference(
        session,
        User,
        event.resolved_by_user_id,
        field="resolved_by_user_id",
        entity_type=entity_type,
        entity_id=entity_id,
        required=False,
        record_event=record_event,
    )
    require_timestamp_order(
        event.created_at,
        event.resolved_at,
        session=session,
        earlier_field="created_at",
        later_field="resolved_at",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require(
        (resolution == ValidationResolutionStatus.OPEN and event.resolved_at is None)
        or (
            resolution != ValidationResolutionStatus.OPEN
            and event.resolved_at is not None
        ),
        session=session,
        code="VALIDATION_RESOLUTION_MISMATCH",
        message="resolved_at must be set only for resolved or waived events",
        entity_type=entity_type,
        entity_id=entity_id,
        field="resolved_at",
        details={"resolution_status": resolution.value},
        record_event=record_event,
    )
    return event


def validate_audit_event(
    session: Session,
    event: AuditEvent,
    *,
    record_event: bool = True,
) -> AuditEvent:
    """Validate an append-only audit event."""

    entity_type = "audit_event"
    entity_id = event.id
    require_non_blank(
        event.event_type,
        session=session,
        field="event_type",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_non_blank(
        event.entity_type,
        session=session,
        field="entity_type",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_non_blank(
        event.summary,
        session=session,
        field="summary",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_reference(
        session,
        User,
        event.actor_user_id,
        field="actor_user_id",
        entity_type=entity_type,
        entity_id=entity_id,
        required=False,
        record_event=record_event,
    )
    require_timestamp(
        event.occurred_at,
        session=session,
        field="occurred_at",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    return event
