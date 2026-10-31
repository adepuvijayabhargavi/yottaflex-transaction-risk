"""Dataset generation run records."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, CheckConstraint, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, UTCDateTime, table_args
from .enums import DatasetRunStatus, enum_type


class DatasetRun(Base):
    """A reproducible synthetic-dataset generation run."""

    __tablename__ = "dataset_runs"

    run_reference: Mapped[str] = mapped_column(
        String(40),
        unique=True,
        nullable=False,
    )
    profile_name: Mapped[str] = mapped_column(String(32), nullable=False)
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[DatasetRunStatus] = mapped_column(
        enum_type(DatasetRunStatus, "dataset_run_status"),
        default=DatasetRunStatus.RUNNING,
        nullable=False,
    )
    reference_datetime_utc: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
    )
    record_counts: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    checksums: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    error_message: Mapped[str | None] = mapped_column(Text)

    __table_args__ = table_args(
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="completed_after_started",
        ),
        Index("ix_dataset_runs_profile_name", "profile_name"),
        Index("ix_dataset_runs_started_at", "started_at"),
        Index("ix_dataset_runs_status_started_at", "status", "started_at"),
    )
