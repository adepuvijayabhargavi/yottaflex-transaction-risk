"""Separate declarative base for evaluation-only tables."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Integer
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db

SCHEMA = "yottaflex_eval"
BIND_KEY = "eval"

BigIntType = BigInteger().with_variant(Integer, "sqlite")
UTCDateTime = DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def utc_now() -> datetime:
    """Return the current UTC time as a MySQL-compatible naive datetime."""

    return datetime.now(UTC).replace(tzinfo=None)


def table_args(
    *constraints: Any,
    **table_options: Any,
) -> tuple[Any, ...] | dict[str, Any]:
    """Return evaluation table options merged with model-specific settings."""

    options: dict[str, Any] = {
        "schema": SCHEMA,
        "mysql_engine": "InnoDB",
        "mysql_charset": "utf8mb4",
    }
    options.update(table_options)
    if constraints:
        return (*constraints, options)
    return options


class EvaluationBase(db.Model):
    """Base class for every evaluation-only table in yottaflex_eval."""

    __abstract__ = True
    __bind_key__ = BIND_KEY

    id: Mapped[int] = mapped_column(
        BigIntType,
        primary_key=True,
        autoincrement=True,
    )
