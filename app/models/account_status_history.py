"""Append-only account status history."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
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
from .enums import AccountStatus, enum_type

if TYPE_CHECKING:
    from .account import Account
    from .user import User


class AccountStatusHistory(AppendOnlyMixin, Base):
    """A permanent record of an account status change."""

    __tablename__ = "account_status_history"

    account_id: Mapped[int] = mapped_column(
        BigIntType,
        ForeignKey(f"{SCHEMA}.accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    previous_status: Mapped[AccountStatus | None] = mapped_column(
        enum_type(AccountStatus, "account_history_previous_status"),
    )
    new_status: Mapped[AccountStatus] = mapped_column(
        enum_type(AccountStatus, "account_history_new_status"),
        nullable=False,
    )
    reason: Mapped[str | None] = mapped_column(String(255))
    changed_by_user_id: Mapped[int | None] = mapped_column(
        BigIntType,
        ForeignKey(f"{SCHEMA}.users.id", ondelete="RESTRICT"),
    )
    changed_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        default=utc_now,
        nullable=False,
    )

    account: Mapped[Account] = relationship(
        "Account",
        back_populates="status_history",
    )
    changed_by: Mapped[User | None] = relationship("User")

    __table_args__ = table_args(
        CheckConstraint(
            "previous_status IS NULL OR previous_status <> new_status",
            name="status_actually_changed",
        ),
        Index(
            "ix_account_status_history_changed_by_user_id",
            "changed_by_user_id",
        ),
        Index("ix_account_status_history_changed_at", "changed_at"),
        Index(
            "ix_account_status_history_account_changed_at",
            "account_id",
            "changed_at",
        ),
    )
