"""Analyst investigation cases."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import (
    SCHEMA,
    Base,
    BigIntType,
    TimestampMixin,
    UTCDateTime,
    table_args,
    utc_now,
)
from .enums import CasePriority, CaseStatus, enum_type

if TYPE_CHECKING:
    from .case_alert import CaseAlert
    from .case_decision import CaseDecision
    from .case_note import CaseNote
    from .user import User


class Case(TimestampMixin, Base):
    """A case that groups related alerts for investigation."""

    __tablename__ = "cases"

    case_reference: Mapped[str] = mapped_column(
        String(40),
        unique=True,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[CaseStatus] = mapped_column(
        enum_type(CaseStatus, "case_status"),
        default=CaseStatus.OPEN,
        nullable=False,
    )
    priority: Mapped[CasePriority] = mapped_column(
        enum_type(CasePriority, "case_priority"),
        default=CasePriority.MEDIUM,
        nullable=False,
    )
    assigned_to_user_id: Mapped[int | None] = mapped_column(
        BigIntType,
        ForeignKey(f"{SCHEMA}.users.id", ondelete="RESTRICT"),
    )
    opened_by_user_id: Mapped[int] = mapped_column(
        BigIntType,
        ForeignKey(f"{SCHEMA}.users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    opened_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        default=utc_now,
        nullable=False,
    )
    closed_by_user_id: Mapped[int | None] = mapped_column(
        BigIntType,
        ForeignKey(f"{SCHEMA}.users.id", ondelete="RESTRICT"),
    )
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    assigned_to: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[assigned_to_user_id],
    )
    opened_by: Mapped[User] = relationship(
        "User",
        foreign_keys=[opened_by_user_id],
    )
    closed_by: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[closed_by_user_id],
    )
    case_alerts: Mapped[list[CaseAlert]] = relationship(
        "CaseAlert",
        back_populates="case",
    )
    notes: Mapped[list[CaseNote]] = relationship(
        "CaseNote",
        back_populates="case",
    )
    decisions: Mapped[list[CaseDecision]] = relationship(
        "CaseDecision",
        back_populates="case",
    )

    __table_args__ = table_args(
        CheckConstraint(
            "closed_at IS NULL OR closed_at >= opened_at",
            name="closed_after_opened",
        ),
        CheckConstraint(
            "(status = 'CLOSED' AND closed_at IS NOT NULL) "
            "OR (status <> 'CLOSED' AND closed_at IS NULL)",
            name="closed_at_matches_status",
        ),
        Index("ix_cases_priority", "priority"),
        Index("ix_cases_opened_by_user_id", "opened_by_user_id"),
        Index("ix_cases_closed_by_user_id", "closed_by_user_id"),
        Index("ix_cases_opened_at", "opened_at"),
        Index("ix_cases_status_opened_at", "status", "opened_at"),
        Index(
            "ix_cases_assigned_status_opened_at",
            "assigned_to_user_id",
            "status",
            "opened_at",
        ),
    )
