"""Groups of transfer transactions that must reconcile."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import (
    SCHEMA,
    Base,
    BigIntType,
    Money,
    TimestampMixin,
    UTCDateTime,
    table_args,
)
from .enums import CurrencyCode, TransferStatus, enum_type

if TYPE_CHECKING:
    from .customer import Customer
    from .transaction import Transaction


class TransferGroup(TimestampMixin, Base):
    """A logical group of transfer legs."""

    __tablename__ = "transfer_groups"

    transfer_reference: Mapped[str] = mapped_column(
        String(40),
        unique=True,
        nullable=False,
    )
    initiated_by_customer_id: Mapped[int | None] = mapped_column(
        BigIntType,
        ForeignKey(f"{SCHEMA}.customers.id", ondelete="RESTRICT"),
    )
    status: Mapped[TransferStatus] = mapped_column(
        enum_type(TransferStatus, "transfer_status"),
        default=TransferStatus.PENDING,
        nullable=False,
    )
    expected_total: Mapped[Decimal] = mapped_column(
        Money,
        nullable=False,
    )
    actual_total: Mapped[Decimal] = mapped_column(
        Money,
        default=0,
        nullable=False,
    )
    currency: Mapped[CurrencyCode] = mapped_column(
        enum_type(CurrencyCode, "transfer_currency"),
        nullable=False,
    )
    reconciled_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    initiated_by_customer: Mapped[Customer | None] = relationship(
        "Customer",
        back_populates="transfer_groups",
    )
    transactions: Mapped[list[Transaction]] = relationship(
        "Transaction",
        back_populates="transfer_group",
    )

    __table_args__ = table_args(
        CheckConstraint("expected_total >= 0", name="expected_total_non_negative"),
        CheckConstraint("actual_total >= 0", name="actual_total_non_negative"),
        CheckConstraint(
            "status <> 'RECONCILED' OR reconciled_at IS NOT NULL",
            name="reconciled_status_has_timestamp",
        ),
        CheckConstraint(
            "status <> 'RECONCILED' OR actual_total = expected_total",
            name="reconciled_totals_match",
        ),
        Index("ix_transfer_groups_customer_id", "initiated_by_customer_id"),
        Index("ix_transfer_groups_status", "status"),
    )
