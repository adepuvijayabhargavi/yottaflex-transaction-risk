"""Merchants that receive card or account payments."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, table_args
from .enums import MerchantRiskLevel, enum_type

if TYPE_CHECKING:
    from .transaction import Transaction


class Merchant(TimestampMixin, Base):
    """A business that can receive transactions."""

    __tablename__ = "merchants"

    merchant_reference: Mapped[str] = mapped_column(
        String(30),
        unique=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str | None] = mapped_column(String(80))
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    risk_level: Mapped[MerchantRiskLevel] = mapped_column(
        enum_type(MerchantRiskLevel, "merchant_risk_level"),
        default=MerchantRiskLevel.STANDARD,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    transactions: Mapped[list[Transaction]] = relationship(
        "Transaction",
        back_populates="merchant",
    )

    __table_args__ = table_args()
