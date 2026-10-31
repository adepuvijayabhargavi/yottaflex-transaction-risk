"""Business transactions processed by the bank."""

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
from .enums import (
    AccountStatus,
    CurrencyCode,
    TransactionStatus,
    TransactionType,
    enum_type,
)

if TYPE_CHECKING:
    from .account import Account
    from .alert import Alert
    from .device import Device
    from .merchant import Merchant
    from .risk_assessment import RiskAssessment
    from .transfer_group import TransferGroup
    from .validation_event import ValidationEvent


class Transaction(TimestampMixin, Base):
    """A single debit, credit, or internal transfer transaction."""

    __tablename__ = "transactions"

    transaction_reference: Mapped[str] = mapped_column(
        String(40),
        unique=True,
        nullable=False,
    )
    transfer_group_id: Mapped[int | None] = mapped_column(
        BigIntType,
        ForeignKey(f"{SCHEMA}.transfer_groups.id", ondelete="RESTRICT"),
    )
    debit_account_id: Mapped[int | None] = mapped_column(
        BigIntType,
        ForeignKey(f"{SCHEMA}.accounts.id", ondelete="RESTRICT"),
    )
    credit_account_id: Mapped[int | None] = mapped_column(
        BigIntType,
        ForeignKey(f"{SCHEMA}.accounts.id", ondelete="RESTRICT"),
    )
    merchant_id: Mapped[int | None] = mapped_column(
        BigIntType,
        ForeignKey(f"{SCHEMA}.merchants.id", ondelete="RESTRICT"),
    )
    device_id: Mapped[int | None] = mapped_column(
        BigIntType,
        ForeignKey(f"{SCHEMA}.devices.id", ondelete="RESTRICT"),
    )
    transaction_type: Mapped[TransactionType] = mapped_column(
        enum_type(TransactionType, "transaction_type"),
        nullable=False,
    )
    status: Mapped[TransactionStatus] = mapped_column(
        enum_type(TransactionStatus, "transaction_status"),
        default=TransactionStatus.POSTED,
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    currency: Mapped[CurrencyCode] = mapped_column(
        enum_type(CurrencyCode, "transaction_currency"),
        nullable=False,
    )
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    debit_account_status_snapshot: Mapped[AccountStatus | None] = mapped_column(
        enum_type(AccountStatus, "transaction_debit_status_snapshot"),
    )
    credit_account_status_snapshot: Mapped[AccountStatus | None] = mapped_column(
        enum_type(AccountStatus, "transaction_credit_status_snapshot"),
    )

    transfer_group: Mapped[TransferGroup | None] = relationship(
        "TransferGroup",
        back_populates="transactions",
    )
    debit_account: Mapped[Account | None] = relationship(
        "Account",
        foreign_keys=[debit_account_id],
        back_populates="debit_transactions",
    )
    credit_account: Mapped[Account | None] = relationship(
        "Account",
        foreign_keys=[credit_account_id],
        back_populates="credit_transactions",
    )
    merchant: Mapped[Merchant | None] = relationship(
        "Merchant",
        back_populates="transactions",
    )
    device: Mapped[Device | None] = relationship(
        "Device",
        back_populates="transactions",
    )
    assessments: Mapped[list[RiskAssessment]] = relationship(
        "RiskAssessment",
        back_populates="transaction",
    )
    alerts: Mapped[list[Alert]] = relationship(
        "Alert",
        back_populates="transaction",
    )
    validation_events: Mapped[list[ValidationEvent]] = relationship(
        "ValidationEvent",
        back_populates="transaction",
    )

    __table_args__ = table_args(
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(
            "(transaction_type = 'OUTGOING' "
            "AND debit_account_id IS NOT NULL AND credit_account_id IS NULL) "
            "OR (transaction_type = 'INCOMING' "
            "AND debit_account_id IS NULL AND credit_account_id IS NOT NULL) "
            "OR (transaction_type = 'INTERNAL' "
            "AND debit_account_id IS NOT NULL AND credit_account_id IS NOT NULL "
            "AND debit_account_id <> credit_account_id)",
            name="accounts_match_transaction_type",
        ),
        CheckConstraint(
            "(debit_account_id IS NULL AND debit_account_status_snapshot IS NULL) "
            "OR (debit_account_id IS NOT NULL "
            "AND debit_account_status_snapshot IS NOT NULL "
            "AND debit_account_status_snapshot <> 'CLOSED')",
            name="debit_status_snapshot_required",
        ),
        CheckConstraint(
            "(credit_account_id IS NULL AND credit_account_status_snapshot IS NULL) "
            "OR (credit_account_id IS NOT NULL "
            "AND credit_account_status_snapshot IS NOT NULL "
            "AND credit_account_status_snapshot <> 'CLOSED')",
            name="credit_status_snapshot_required",
        ),
        Index("ix_transactions_transfer_group_id", "transfer_group_id"),
        Index("ix_transactions_merchant_id", "merchant_id"),
        Index("ix_transactions_device_id", "device_id"),
        Index("ix_transactions_occurred_at", "occurred_at"),
        Index("ix_transactions_status", "status"),
        Index(
            "ix_transactions_debit_account_occurred_at",
            "debit_account_id",
            "occurred_at",
        ),
        Index(
            "ix_transactions_credit_account_occurred_at",
            "credit_account_id",
            "occurred_at",
        ),
    )
