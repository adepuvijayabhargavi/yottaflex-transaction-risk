"""Append-only case decisions."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Text
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
from .enums import CaseDecisionType, enum_type

if TYPE_CHECKING:
    from .alert import Alert
    from .case import Case
    from .user import User


class CaseDecision(AppendOnlyMixin, Base):
    """An immutable analyst disposition recorded for a case."""

    __tablename__ = "case_decisions"

    case_id: Mapped[int] = mapped_column(
        BigIntType,
        ForeignKey(f"{SCHEMA}.cases.id", ondelete="RESTRICT"),
        nullable=False,
    )
    decided_by_user_id: Mapped[int] = mapped_column(
        BigIntType,
        ForeignKey(f"{SCHEMA}.users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    decision: Mapped[CaseDecisionType] = mapped_column(
        enum_type(CaseDecisionType, "case_decision_type"),
        nullable=False,
    )
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        default=utc_now,
        nullable=False,
    )
    triggering_alert_id: Mapped[int] = mapped_column(
        BigIntType,
        ForeignKey(f"{SCHEMA}.alerts.id", ondelete="RESTRICT"),
        nullable=False,
    )

    case: Mapped[Case] = relationship("Case", back_populates="decisions")
    decided_by: Mapped[User] = relationship("User")
    triggering_alert: Mapped[Alert] = relationship("Alert")

    __table_args__ = table_args(
        Index("ix_case_decisions_decided_by_user_id", "decided_by_user_id"),
        Index("ix_case_decisions_triggering_alert_id", "triggering_alert_id"),
        Index("ix_case_decisions_decided_at", "decided_at"),
        Index("ix_case_decisions_decision", "decision"),
        Index("ix_case_decisions_case_id_decided_at", "case_id", "decided_at"),
    )
