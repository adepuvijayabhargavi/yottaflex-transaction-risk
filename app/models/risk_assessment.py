"""Risk-engine assessments for transactions."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import (
    SCHEMA,
    Base,
    BigIntType,
    CreatedAtMixin,
    UTCDateTime,
    table_args,
    utc_now,
)
from .enums import AssessmentStatus, RiskLevel, enum_type

if TYPE_CHECKING:
    from .alert import Alert
    from .risk_finding import RiskFinding
    from .transaction import Transaction


class RiskAssessment(CreatedAtMixin, Base):
    """The aggregate risk score produced for one transaction."""

    __tablename__ = "risk_assessments"

    transaction_id: Mapped[int] = mapped_column(
        BigIntType,
        ForeignKey(f"{SCHEMA}.transactions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_level: Mapped[RiskLevel] = mapped_column(
        enum_type(RiskLevel, "risk_assessment_level"),
        nullable=False,
    )
    status: Mapped[AssessmentStatus] = mapped_column(
        enum_type(AssessmentStatus, "risk_assessment_status"),
        default=AssessmentStatus.COMPLETED,
        nullable=False,
    )
    assessed_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        default=utc_now,
        nullable=False,
    )
    explanation: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    transaction: Mapped[Transaction] = relationship(
        "Transaction",
        back_populates="assessments",
    )
    findings: Mapped[list[RiskFinding]] = relationship(
        "RiskFinding",
        back_populates="assessment",
    )
    alerts: Mapped[list[Alert]] = relationship(
        "Alert",
        back_populates="assessment",
    )

    __table_args__ = table_args(
        UniqueConstraint(
            "transaction_id",
            "model_version",
            name="uq_risk_assessments_transaction_model_version",
        ),
        CheckConstraint("score >= 0 AND score <= 100", name="score_range"),
        Index("ix_risk_assessments_risk_level", "risk_level"),
        Index("ix_risk_assessments_assessed_at", "assessed_at"),
        Index(
            "ix_risk_assessments_transaction_assessed_at",
            "transaction_id",
            "assessed_at",
        ),
    )
