"""Shared validation helpers."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, NoReturn, TypeVar

from sqlalchemy.orm import Session

from .errors import ValidationError, ValidationIssue
from .recording import record_validation_issue

T = TypeVar("T", bound=StrEnum)


def fail(
    session: Session | None,
    issue: ValidationIssue,
    *,
    record_event: bool = True,
    transaction_id: int | None = None,
) -> NoReturn:
    """Record the issue when requested, then raise it."""

    if session is not None and record_event:
        record_validation_issue(
            session,
            issue,
            transaction_id=transaction_id,
        )
    raise ValidationError(issue)


def require(
    condition: bool,
    *,
    session: Session | None,
    code: str,
    message: str,
    entity_type: str,
    entity_id: int | None = None,
    field: str | None = None,
    details: dict[str, Any] | None = None,
    record_event: bool = True,
    transaction_id: int | None = None,
) -> None:
    """Raise a validation issue when a condition is false."""

    if condition:
        return
    fail(
        session,
        ValidationIssue(
            code=code,
            message=message,
            entity_type=entity_type,
            entity_id=entity_id,
            field=field,
            details=details or {},
        ),
        record_event=record_event,
        transaction_id=transaction_id,
    )


def require_non_blank(
    value: str | None,
    *,
    session: Session | None,
    field: str,
    entity_type: str,
    entity_id: int | None = None,
    code: str = "MISSING_REQUIRED_FIELD",
    record_event: bool = True,
    transaction_id: int | None = None,
) -> str:
    """Require a non-empty string."""

    require(
        isinstance(value, str) and bool(value.strip()),
        session=session,
        code=code,
        message=f"{field} is required",
        entity_type=entity_type,
        entity_id=entity_id,
        field=field,
        record_event=record_event,
        transaction_id=transaction_id,
    )
    return value.strip()


def require_enum(
    value: T | str | None,
    enum_class: type[T],
    *,
    session: Session | None,
    field: str,
    entity_type: str,
    entity_id: int | None = None,
    record_event: bool = True,
    transaction_id: int | None = None,
) -> T:
    """Require a value from an application enum."""

    try:
        return enum_class(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        fail(
            session,
            ValidationIssue(
                code="INVALID_ENUM_VALUE",
                message=f"{field} has an invalid value",
                entity_type=entity_type,
                entity_id=entity_id,
                field=field,
                details={
                    "value": str(value),
                    "allowed": [item.value for item in enum_class],
                },
            ),
            record_event=record_event,
            transaction_id=transaction_id,
        )


def require_int_range(
    value: int | None,
    *,
    minimum: int,
    maximum: int,
    session: Session | None,
    field: str,
    entity_type: str,
    entity_id: int | None = None,
    code: str = "VALUE_OUT_OF_RANGE",
    record_event: bool = True,
    transaction_id: int | None = None,
) -> int:
    """Require an integer within an inclusive range."""

    require(
        isinstance(value, int) and not isinstance(value, bool),
        session=session,
        code=code,
        message=f"{field} must be an integer",
        entity_type=entity_type,
        entity_id=entity_id,
        field=field,
        record_event=record_event,
        transaction_id=transaction_id,
    )
    require(
        minimum <= value <= maximum,
        session=session,
        code=code,
        message=f"{field} must be between {minimum} and {maximum}",
        entity_type=entity_type,
        entity_id=entity_id,
        field=field,
        details={"value": value, "minimum": minimum, "maximum": maximum},
        record_event=record_event,
        transaction_id=transaction_id,
    )
    return value


def as_decimal(value: Any) -> Decimal | None:
    """Convert a numeric value to Decimal without accepting booleans."""

    if value is None or isinstance(value, bool):
        return None
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def require_money(
    value: Any,
    *,
    session: Session | None,
    field: str,
    entity_type: str,
    entity_id: int | None = None,
    positive: bool = False,
    allow_negative: bool = False,
    record_event: bool = True,
    transaction_id: int | None = None,
) -> Decimal:
    """Require a decimal amount, optionally strictly positive or signed."""

    amount = as_decimal(value)
    require(
        amount is not None,
        session=session,
        code="INVALID_AMOUNT",
        message=f"{field} must be a numeric amount",
        entity_type=entity_type,
        entity_id=entity_id,
        field=field,
        record_event=record_event,
        transaction_id=transaction_id,
    )
    if positive:
        require(
            amount > 0,
            session=session,
            code="NON_POSITIVE_AMOUNT",
            message=f"{field} must be greater than zero",
            entity_type=entity_type,
            entity_id=entity_id,
            field=field,
            details={"value": str(amount)},
            record_event=record_event,
            transaction_id=transaction_id,
        )
    elif not allow_negative:
        require(
            amount >= 0,
            session=session,
            code="NEGATIVE_AMOUNT",
            message=f"{field} must not be negative",
            entity_type=entity_type,
            entity_id=entity_id,
            field=field,
            details={"value": str(amount)},
            record_event=record_event,
            transaction_id=transaction_id,
        )
    return amount


def require_timestamp(
    value: datetime | None,
    *,
    session: Session | None,
    field: str,
    entity_type: str,
    entity_id: int | None = None,
    code: str = "MISSING_TIMESTAMP",
    record_event: bool = True,
    transaction_id: int | None = None,
) -> datetime:
    """Require a datetime value."""

    require(
        isinstance(value, datetime),
        session=session,
        code=code,
        message=f"{field} must be a timestamp",
        entity_type=entity_type,
        entity_id=entity_id,
        field=field,
        record_event=record_event,
        transaction_id=transaction_id,
    )
    return value


def require_timestamp_order(
    earlier: datetime | None,
    later: datetime | None,
    *,
    session: Session | None,
    earlier_field: str,
    later_field: str,
    entity_type: str,
    entity_id: int | None = None,
    code: str = "INVALID_TIMESTAMP_ORDER",
    record_event: bool = True,
    transaction_id: int | None = None,
) -> None:
    """Require the second timestamp to be at or after the first."""

    if earlier is None or later is None:
        return
    require(
        later >= earlier,
        session=session,
        code=code,
        message=f"{later_field} must not be before {earlier_field}",
        entity_type=entity_type,
        entity_id=entity_id,
        field=later_field,
        details={
            earlier_field: earlier.isoformat(),
            later_field: later.isoformat(),
        },
        record_event=record_event,
        transaction_id=transaction_id,
    )


def require_reference(
    session: Session | None,
    model: type[Any],
    value: Any,
    *,
    field: str,
    entity_type: str,
    entity_id: int | None = None,
    required: bool = True,
    code: str = "REFERENCE_NOT_FOUND",
    record_event: bool = True,
    transaction_id: int | None = None,
) -> Any:
    """Resolve a primary-key reference to an existing record."""

    if value is None:
        if not required:
            return None
        fail(
            session,
            ValidationIssue(
                code="MISSING_REFERENCE",
                message=f"{field} is required",
                entity_type=entity_type,
                entity_id=entity_id,
                field=field,
            ),
            record_event=record_event,
            transaction_id=transaction_id,
        )

    primary_key = value if isinstance(value, int) else getattr(value, "id", None)
    if primary_key is None:
        fail(
            session,
            ValidationIssue(
                code="UNSAVED_REFERENCE",
                message=f"{field} must reference a saved record",
                entity_type=entity_type,
                entity_id=entity_id,
                field=field,
            ),
            record_event=record_event,
            transaction_id=transaction_id,
        )

    if session is None:
        return value

    referenced = session.get(model, primary_key)
    if referenced is None:
        fail(
            session,
            ValidationIssue(
                code=code,
                message=f"{field} references a missing record",
                entity_type=entity_type,
                entity_id=entity_id,
                field=field,
                details={"model": model.__name__, "id": primary_key},
            ),
            record_event=record_event,
            transaction_id=transaction_id,
        )
    return referenced


def validate_primary_key_reference(
    session: Session,
    model: type[Any],
    primary_key: int | None,
    *,
    field: str = "id",
    entity_type: str | None = None,
    record_event: bool = True,
) -> Any:
    """Validate that a primary-key value resolves to a stored record."""

    return require_reference(
        session,
        model,
        primary_key,
        field=field,
        entity_type=entity_type or model.__name__.lower(),
        entity_id=primary_key,
        record_event=record_event,
    )
