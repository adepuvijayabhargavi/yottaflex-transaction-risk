"""Customer devices used to initiate transactions."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import SCHEMA, Base, BigIntType, TimestampMixin, UTCDateTime, table_args
from .enums import DeviceType, enum_type

if TYPE_CHECKING:
    from .customer import Customer
    from .transaction import Transaction


class Device(TimestampMixin, Base):
    """A device fingerprint associated with a customer."""

    __tablename__ = "devices"

    device_fingerprint: Mapped[str] = mapped_column(
        String(128),
        unique=True,
        nullable=False,
    )
    customer_id: Mapped[int] = mapped_column(
        BigIntType,
        ForeignKey(f"{SCHEMA}.customers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    device_type: Mapped[DeviceType] = mapped_column(
        enum_type(DeviceType, "device_type"),
        default=DeviceType.UNKNOWN,
        nullable=False,
    )
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    is_trusted: Mapped[bool] = mapped_column(default=False, nullable=False)

    customer: Mapped[Customer] = relationship(
        "Customer",
        back_populates="devices",
    )
    transactions: Mapped[list[Transaction]] = relationship(
        "Transaction",
        back_populates="device",
    )

    __table_args__ = table_args(
        CheckConstraint(
            "last_seen_at >= first_seen_at",
            name="last_seen_after_first_seen",
        ),
        Index("ix_devices_customer_id", "customer_id"),
    )
