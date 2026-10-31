"""Individual rule findings from a risk assessment."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import SCHEMA, Base, BigIntType, CreatedAtMixin, table_args
from .enums import RiskSeverity, enum_type

if TYPE_CHECKING:
    from .alert import Alert
    from .risk_assessment import RiskAssessment
    from .risk_rule import RiskRule


class RiskFinding(CreatedAtMixin, Base):
    """An explainable finding produced by one risk rule."""

    __tablename__ = "risk_findings"

    assessment_id: Mapped[int] = mapped_column(
        BigIntType,
        ForeignKey(f"{SCHEMA}.risk_assessments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    rule_id: Mapped[int] = mapped_column(
        BigIntType,
        ForeignKey(f"{SCHEMA}.risk_rules.id", ondelete="RESTRICT"),
        nullable=False,
    )
    rule_code: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    severity: Mapped[RiskSeverity] = mapped_column(
        enum_type(RiskSeverity, "risk_finding_severity"),
        nullable=False,
    )
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    assessment: Mapped[RiskAssessment] = relationship(
        "RiskAssessment",
        back_populates="findings",
    )
    rule: Mapped[RiskRule] = relationship(
        "RiskRule",
        back_populates="findings",
    )
    alert: Mapped[Alert | None] = relationship(
        "Alert",
        back_populates="finding",
        uselist=False,
    )

    __table_args__ = table_args(
        UniqueConstraint(
            "assessment_id",
            "rule_id",
            name="uq_risk_findings_assessment_rule",
        ),
        CheckConstraint("score >= 0 AND score <= 100", name="score_range"),
        Index("ix_risk_findings_rule_id", "rule_id"),
        Index("ix_risk_findings_severity", "severity"),
    )
