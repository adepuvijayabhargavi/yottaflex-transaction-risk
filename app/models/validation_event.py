"""Records of rejected or flagged data-validity problems."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import SCHEMA, Base, BigIntType, CreatedAtMixin, UTCDateTime, table_args
from .enums import (
    ValidationResolutionStatus,
    ValidationSeverity,
    enum_type,
)

if TYPE_CHECKING:
    from .transaction import Transaction
    from .user import User


class ValidationEvent(CreatedAtMixin, Base):
    """An immutable validation record with mutable resolution fields."""

    __tablename__ = "validation_events"

    event_reference: Mapped[str] = mapped_column(
        String(40),
        unique=True,
        nullable=False,
    )
    validation_code: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[ValidationSeverity] = mapped_column(
        enum_type(ValidationSeverity, "validation_severity"),
        default=ValidationSeverity.ERROR,
        nullable=False,
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[int | None] = mapped_column(BigIntType)
    transaction_id: Mapped[int | None] = mapped_column(
        BigIntType,
        ForeignKey(f"{SCHEMA}.transactions.id", ondelete="RESTRICT"),
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    resolution_status: Mapped[ValidationResolutionStatus] = mapped_column(
        enum_type(
            ValidationResolutionStatus,
            "validation_resolution_status",
        ),
        default=ValidationResolutionStatus.OPEN,
        nullable=False,
    )
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_by_user_id: Mapped[int | None] = mapped_column(
        BigIntType,
        ForeignKey(f"{SCHEMA}.users.id", ondelete="RESTRICT"),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    transaction: Mapped[Transaction | None] = relationship(
        "Transaction",
        back_populates="validation_events",
    )
    resolved_by: Mapped[User | None] = relationship("User")

    __table_args__ = table_args(
        CheckConstraint(
            "resolved_at IS NULL OR resolved_at >= created_at",
            name="resolved_after_created",
        ),
        Index("ix_validation_events_validation_code", "validation_code"),
        Index("ix_validation_events_transaction_id", "transaction_id"),
        Index("ix_validation_events_resolved_by_user_id", "resolved_by_user_id"),
        Index("ix_validation_events_created_at", "created_at"),
        Index(
            "ix_validation_events_entity_created_at",
            "entity_type",
            "entity_id",
            "created_at",
        ),
        Index(
            "ix_validation_events_resolution_created_at",
            "resolution_status",
            "created_at",
        ),
    )
