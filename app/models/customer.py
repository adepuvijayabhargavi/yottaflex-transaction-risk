"""Bank customers."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, table_args
from .enums import CustomerRiskSegment, enum_type

if TYPE_CHECKING:
    from .account import Account
    from .device import Device
    from .transfer_group import TransferGroup


class Customer(TimestampMixin, Base):
    """A customer who owns one or more accounts."""

    __tablename__ = "customers"

    customer_reference: Mapped[str] = mapped_column(
        String(30),
        unique=True,
        nullable=False,
    )
    first_name: Mapped[str] = mapped_column(String(80), nullable=False)
    last_name: Mapped[str] = mapped_column(String(80), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    phone: Mapped[str | None] = mapped_column(String(30))
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    risk_segment: Mapped[CustomerRiskSegment] = mapped_column(
        enum_type(CustomerRiskSegment, "customer_risk_segment"),
        default=CustomerRiskSegment.STANDARD,
        nullable=False,
    )
    onboarding_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    accounts: Mapped[list[Account]] = relationship(
        "Account",
        back_populates="customer",
    )
    devices: Mapped[list[Device]] = relationship(
        "Device",
        back_populates="customer",
    )
    transfer_groups: Mapped[list[TransferGroup]] = relationship(
        "TransferGroup",
        back_populates="initiated_by_customer",
    )

    __table_args__ = table_args()
