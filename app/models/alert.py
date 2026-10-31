"""Alerts raised for risky transactions."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import SCHEMA, Base, BigIntType, TimestampMixin, UTCDateTime, table_args
from .enums import AlertPriority, AlertStatus, enum_type

if TYPE_CHECKING:
    from .case_alert import CaseAlert
    from .risk_assessment import RiskAssessment
    from .risk_finding import RiskFinding
    from .risk_rule import RiskRule
    from .transaction import Transaction
    from .user import User


class Alert(TimestampMixin, Base):
    """An alert linked to a transaction, assessment, finding, and rule."""

    __tablename__ = "alerts"

    alert_reference: Mapped[str] = mapped_column(
        String(40),
        unique=True,
        nullable=False,
    )
    transaction_id: Mapped[int] = mapped_column(
        BigIntType,
        ForeignKey(f"{SCHEMA}.transactions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    assessment_id: Mapped[int] = mapped_column(
        BigIntType,
        ForeignKey(f"{SCHEMA}.risk_assessments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    finding_id: Mapped[int] = mapped_column(
        BigIntType,
        ForeignKey(f"{SCHEMA}.risk_findings.id", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )
    triggering_rule_id: Mapped[int] = mapped_column(
        BigIntType,
        ForeignKey(f"{SCHEMA}.risk_rules.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[AlertStatus] = mapped_column(
        enum_type(AlertStatus, "alert_status"),
        default=AlertStatus.OPEN,
        nullable=False,
    )
    priority: Mapped[AlertPriority] = mapped_column(
        enum_type(AlertPriority, "alert_priority"),
        default=AlertPriority.MEDIUM,
        nullable=False,
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[str] = mapped_column(String(255), nullable=False)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    assigned_to_user_id: Mapped[int | None] = mapped_column(
        BigIntType,
        ForeignKey(f"{SCHEMA}.users.id", ondelete="RESTRICT"),
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    transaction: Mapped[Transaction] = relationship(
        "Transaction",
        back_populates="alerts",
    )
    assessment: Mapped[RiskAssessment] = relationship(
        "RiskAssessment",
        back_populates="alerts",
    )
    finding: Mapped[RiskFinding] = relationship(
        "RiskFinding",
        back_populates="alert",
    )
    triggering_rule: Mapped[RiskRule] = relationship(
        "RiskRule",
        back_populates="triggering_alerts",
    )
    assigned_to: Mapped[User | None] = relationship("User")
    case_links: Mapped[list[CaseAlert]] = relationship(
        "CaseAlert",
        back_populates="alert",
    )

    __table_args__ = table_args(
        CheckConstraint("score >= 0 AND score <= 100", name="score_range"),
        CheckConstraint(
            "acknowledged_at IS NULL OR acknowledged_at >= created_at",
            name="acknowledged_after_created",
        ),
        CheckConstraint(
            "closed_at IS NULL OR closed_at >= created_at",
            name="closed_after_created",
        ),
        CheckConstraint(
            "acknowledged_at IS NULL OR closed_at IS NULL "
            "OR closed_at >= acknowledged_at",
            name="closed_after_acknowledged",
        ),
        Index("ix_alerts_transaction_id", "transaction_id"),
        Index("ix_alerts_assessment_id", "assessment_id"),
        Index("ix_alerts_triggering_rule_id", "triggering_rule_id"),
        Index("ix_alerts_priority", "priority"),
        Index("ix_alerts_created_at", "created_at"),
        Index("ix_alerts_status_created_at", "status", "created_at"),
        Index(
            "ix_alerts_assigned_status_created_at",
            "assigned_to_user_id",
            "status",
            "created_at",
        ),
    )
