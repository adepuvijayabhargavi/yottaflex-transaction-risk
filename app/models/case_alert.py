"""Historical links between cases and alerts."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Computed,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import SCHEMA, Base, BigIntType, UTCDateTime, table_args, utc_now

if TYPE_CHECKING:
    from .alert import Alert
    from .case import Case
    from .user import User


class CaseAlert(Base):
    """A case-to-alert link that becomes inactive instead of being deleted."""

    __tablename__ = "case_alerts"

    case_id: Mapped[int] = mapped_column(
        BigIntType,
        ForeignKey(f"{SCHEMA}.cases.id", ondelete="RESTRICT"),
        nullable=False,
    )
    alert_id: Mapped[int] = mapped_column(
        BigIntType,
        ForeignKey(f"{SCHEMA}.alerts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    linked_by_user_id: Mapped[int] = mapped_column(
        BigIntType,
        ForeignKey(f"{SCHEMA}.users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    linked_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        default=utc_now,
        nullable=False,
    )
    unlinked_by_user_id: Mapped[int | None] = mapped_column(
        BigIntType,
        ForeignKey(f"{SCHEMA}.users.id", ondelete="RESTRICT"),
    )
    unlinked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    unlink_reason: Mapped[str | None] = mapped_column(String(500))
    active_alert_id: Mapped[int | None] = mapped_column(
        BigIntType,
        Computed(
            "CASE WHEN unlinked_at IS NULL THEN alert_id ELSE NULL END",
            persisted=True,
        ),
    )

    case: Mapped[Case] = relationship("Case", back_populates="case_alerts")
    alert: Mapped[Alert] = relationship("Alert", back_populates="case_links")
    linked_by: Mapped[User] = relationship(
        "User",
        foreign_keys=[linked_by_user_id],
    )
    unlinked_by: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[unlinked_by_user_id],
    )

    __table_args__ = table_args(
        UniqueConstraint(
            "active_alert_id",
            name="uq_case_alerts_active_alert_id",
        ),
        CheckConstraint(
            "unlinked_at IS NULL OR unlinked_at >= linked_at",
            name="unlinked_after_linked",
        ),
        CheckConstraint(
            "(unlinked_at IS NULL AND unlinked_by_user_id IS NULL "
            "AND unlink_reason IS NULL) "
            "OR (unlinked_at IS NOT NULL AND unlinked_by_user_id IS NOT NULL "
            "AND unlink_reason IS NOT NULL "
            "AND length(trim(unlink_reason)) > 0)",
            name="unlink_requires_actor_and_reason",
        ),
        Index("ix_case_alerts_case_id_unlinked_at", "case_id", "unlinked_at"),
        Index("ix_case_alerts_alert_id", "alert_id"),
        Index("ix_case_alerts_linked_at", "linked_at"),
        Index("ix_case_alerts_linked_by_user_id", "linked_by_user_id"),
        Index("ix_case_alerts_unlinked_by_user_id", "unlinked_by_user_id"),
    )
