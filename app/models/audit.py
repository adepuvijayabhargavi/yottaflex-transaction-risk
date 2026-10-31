"""Append-only audit events."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import (
    SCHEMA,
    AppendOnlyMixin,
    Base,
    BigIntType,
    UTCDateTime,
    table_args,
    utc_now,
)

if TYPE_CHECKING:
    from .user import User


class AuditEvent(AppendOnlyMixin, Base):
    """A permanent record of an important system or analyst action."""

    __tablename__ = "audit_events"

    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[int | None] = mapped_column(BigIntType)
    actor_user_id: Mapped[int | None] = mapped_column(
        BigIntType,
        ForeignKey(f"{SCHEMA}.users.id", ondelete="RESTRICT"),
    )
    summary: Mapped[str] = mapped_column(String(255), nullable=False)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    request_id: Mapped[str | None] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        default=utc_now,
        nullable=False,
    )

    actor: Mapped[User | None] = relationship(
        "User",
        back_populates="audit_events",
        foreign_keys=[actor_user_id],
    )

    __table_args__ = table_args(
        Index("ix_audit_events_event_type", "event_type"),
        Index(
            "ix_audit_events_entity_occurred_at",
            "entity_type",
            "entity_id",
            "occurred_at",
        ),
        Index("ix_audit_events_actor_user_id", "actor_user_id"),
        Index("ix_audit_events_occurred_at", "occurred_at"),
    )
