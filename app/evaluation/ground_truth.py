"""Evaluation-only fraud labels generated alongside synthetic datasets."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, CheckConstraint, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import EvaluationBase, UTCDateTime, table_args, utc_now


class GroundTruth(EvaluationBase):
    """A fraud label for one generated transaction in one dataset run."""

    __tablename__ = "ground_truth"

    ground_truth_reference: Mapped[str] = mapped_column(String(40), nullable=False)
    dataset_run_reference: Mapped[str] = mapped_column(String(40), nullable=False)
    transaction_reference: Mapped[str] = mapped_column(String(40), nullable=False)
    is_fraud: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    primary_pattern: Mapped[str | None] = mapped_column(String(64))
    pattern_codes: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    label_source: Mapped[str] = mapped_column(
        String(64),
        default="SYNTHETIC_GENERATOR",
        nullable=False,
    )
    generation_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        default=utc_now,
        nullable=False,
    )

    __table_args__ = table_args(
        UniqueConstraint(
            "ground_truth_reference",
            name="uq_ground_truth_reference",
        ),
        UniqueConstraint(
            "dataset_run_reference",
            "transaction_reference",
            name="uq_ground_truth_run_transaction",
        ),
        CheckConstraint(
            "CHAR_LENGTH(TRIM(dataset_run_reference)) > 0",
            name="dataset_run_reference_not_blank",
        ),
        CheckConstraint(
            "CHAR_LENGTH(TRIM(transaction_reference)) > 0",
            name="transaction_reference_not_blank",
        ),
        CheckConstraint(
            "(is_fraud = 0 AND primary_pattern IS NULL) OR "
            "(is_fraud = 1 AND primary_pattern IS NOT NULL "
            "AND CHAR_LENGTH(TRIM(primary_pattern)) > 0)",
            name="primary_pattern_matches_label",
        ),
        CheckConstraint(
            "JSON_TYPE(pattern_codes) = 'ARRAY'",
            name="pattern_codes_is_array",
        ),
        Index("ix_ground_truth_dataset_run_reference", "dataset_run_reference"),
        Index("ix_ground_truth_transaction_reference", "transaction_reference"),
        Index("ix_ground_truth_is_fraud", "is_fraud"),
        Index("ix_ground_truth_primary_pattern", "primary_pattern"),
        Index("ix_ground_truth_created_at", "created_at"),
    )
