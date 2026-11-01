"""Analyst and administrator accounts."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from flask_login import UserMixin
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from werkzeug.security import check_password_hash, generate_password_hash

from .base import Base, TimestampMixin, UTCDateTime, table_args
from .enums import UserRole, enum_type

if TYPE_CHECKING:
    from .audit import AuditEvent


class User(UserMixin, TimestampMixin, Base):
    """A user who can review alerts and manage cases."""

    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        enum_type(UserRole, "user_role"),
        default=UserRole.ANALYST,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    audit_events: Mapped[list[AuditEvent]] = relationship(
        "AuditEvent",
        back_populates="actor",
        foreign_keys="AuditEvent.actor_user_id",
    )

    __table_args__ = table_args()

    def set_password(self, password: str) -> None:
        """Hash and store the user password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Verify the password against the stored hash."""
        return check_password_hash(self.password_hash, password)

    def get_id(self) -> str:
        """Return the user ID string representation for Flask-Login."""
        return str(self.id)
