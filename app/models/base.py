"""Shared declarative base and database column helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Integer, Numeric, event
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db

SCHEMA = "yottaflex"


class AppendOnlyError(RuntimeError):
    """Raised when an append-only record is changed or deleted."""


BigIntType = BigInteger().with_variant(Integer, "sqlite")
UTCDateTime = DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
Money = Numeric(18, 2)


def utc_now() -> datetime:
    """Return the current UTC time as a MySQL-compatible naive datetime."""

    return datetime.now(UTC).replace(tzinfo=None)


def table_args(
    *constraints: Any,
    **table_options: Any,
) -> tuple[Any, ...] | dict[str, Any]:
    """Return common MySQL table options merged with model-specific settings."""

    options: dict[str, Any] = {
        "schema": SCHEMA,
        "mysql_engine": "InnoDB",
        "mysql_charset": "utf8mb4",
    }
    options.update(table_options)
    if constraints:
        return (*constraints, options)
    return options


class AppendOnlyMixin:
    """Reject ORM updates and deletes for historical records."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        event.listen(cls, "before_update", cls._reject_mutation)
        event.listen(cls, "before_delete", cls._reject_mutation)

    @staticmethod
    def _reject_mutation(mapper: object, connection: object, target: object) -> None:
        raise AppendOnlyError(
            f"{type(target).__name__} records are append-only and cannot be changed"
        )


class CreatedAtMixin:
    """Add an immutable creation timestamp."""

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        default=utc_now,
        nullable=False,
    )


class TimestampMixin(CreatedAtMixin):
    """Add creation and last-update timestamps."""

    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class Base(db.Model):
    """Base class for every core table in the yottaflex schema."""

    __abstract__ = True

    id: Mapped[int] = mapped_column(
        BigIntType,
        primary_key=True,
        autoincrement=True,
    )
