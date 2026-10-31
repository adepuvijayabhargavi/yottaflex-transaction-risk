"""Versioned risk-rule definitions."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Computed,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UTCDateTime, table_args, utc_now
from .enums import RiskSeverity, enum_type

if TYPE_CHECKING:
    from .alert import Alert
    from .risk_finding import RiskFinding


class RiskRule(TimestampMixin, Base):
    """A configurable rule used by the risk engine."""

    __tablename__ = "risk_rules"

    code: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[RiskSeverity] = mapped_column(
        enum_type(RiskSeverity, "risk_rule_severity"),
        default=RiskSeverity.MEDIUM,
        nullable=False,
    )
    score_weight: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    configuration: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    active_code: Mapped[str | None] = mapped_column(
        String(64),
        Computed(
            "CASE WHEN is_active THEN code ELSE NULL END",
            persisted=True,
        ),
    )
    effective_from: Mapped[datetime] = mapped_column(
        UTCDateTime,
        default=utc_now,
        nullable=False,
    )
    effective_to: Mapped[datetime | None] = mapped_column(UTCDateTime)

    findings: Mapped[list[RiskFinding]] = relationship(
        "RiskFinding",
        back_populates="rule",
    )
    triggering_alerts: Mapped[list[Alert]] = relationship(
        "Alert",
        back_populates="triggering_rule",
    )

    __table_args__ = table_args(
        UniqueConstraint("code", "version", name="uq_risk_rules_code_version"),
        UniqueConstraint("active_code", name="uq_risk_rules_active_code"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(
            "score_weight >= 0 AND score_weight <= 100",
            name="score_weight_range",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="effective_window_valid",
        ),
        Index("ix_risk_rules_code_is_active", "code", "is_active"),
        Index("ix_risk_rules_category", "category"),
    )
