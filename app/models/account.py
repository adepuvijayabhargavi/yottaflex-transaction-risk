"""Customer bank accounts."""

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
from .enums import AccountStatus, AccountType, CurrencyCode, enum_type

if TYPE_CHECKING:
    from .account_status_history import AccountStatusHistory
    from .customer import Customer
    from .transaction import Transaction


class Account(TimestampMixin, Base):
    """An account that participates in transactions."""

    __tablename__ = "accounts"

    account_number: Mapped[str] = mapped_column(
        String(34),
        unique=True,
        nullable=False,
    )
    customer_id: Mapped[int] = mapped_column(
        BigIntType,
        ForeignKey(f"{SCHEMA}.customers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    account_type: Mapped[AccountType] = mapped_column(
        enum_type(AccountType, "account_type"),
        default=AccountType.CHECKING,
        nullable=False,
    )
    currency: Mapped[CurrencyCode] = mapped_column(
        enum_type(CurrencyCode, "account_currency"),
        nullable=False,
    )
    status: Mapped[AccountStatus] = mapped_column(
        enum_type(AccountStatus, "account_status"),
        default=AccountStatus.ACTIVE,
        nullable=False,
    )
    balance: Mapped[Decimal] = mapped_column(
        Money,
        default=0,
        nullable=False,
    )
    overdraft_limit: Mapped[Decimal] = mapped_column(
        Money,
        default=0,
        nullable=False,
    )
    opened_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    customer: Mapped[Customer] = relationship(
        "Customer",
        back_populates="accounts",
    )
    status_history: Mapped[list[AccountStatusHistory]] = relationship(
        "AccountStatusHistory",
        back_populates="account",
    )
    debit_transactions: Mapped[list[Transaction]] = relationship(
        "Transaction",
        foreign_keys="Transaction.debit_account_id",
        back_populates="debit_account",
    )
    credit_transactions: Mapped[list[Transaction]] = relationship(
        "Transaction",
        foreign_keys="Transaction.credit_account_id",
        back_populates="credit_account",
    )

    __table_args__ = table_args(
        CheckConstraint(
            "overdraft_limit >= 0",
            name="overdraft_limit_non_negative",
        ),
        CheckConstraint(
            "balance >= -overdraft_limit",
            name="balance_within_overdraft",
        ),
        CheckConstraint(
            "(status = 'CLOSED' AND closed_at IS NOT NULL) "
            "OR (status <> 'CLOSED' AND closed_at IS NULL)",
            name="closed_at_matches_status",
        ),
        CheckConstraint(
            "closed_at IS NULL OR closed_at >= opened_at",
            name="closed_after_opened",
        ),
        Index("ix_accounts_customer_id", "customer_id"),
        Index("ix_accounts_status", "status"),
    )
