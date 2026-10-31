"""Append-only case notes."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import (
    SCHEMA,
    AppendOnlyMixin,
    Base,
    BigIntType,
    CreatedAtMixin,
    UTCDateTime,
    table_args,
    utc_now,
)
from .enums import CaseNoteType, enum_type

if TYPE_CHECKING:
    from .case import Case
    from .user import User


class CaseNote(AppendOnlyMixin, CreatedAtMixin, Base):
    """An immutable analyst note attached to a case."""

    __tablename__ = "case_notes"

    case_id: Mapped[int] = mapped_column(
        BigIntType,
        ForeignKey(f"{SCHEMA}.cases.id", ondelete="RESTRICT"),
        nullable=False,
    )
    author_user_id: Mapped[int] = mapped_column(
        BigIntType,
        ForeignKey(f"{SCHEMA}.users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    note_type: Mapped[CaseNoteType] = mapped_column(
        enum_type(CaseNoteType, "case_note_type"),
        default=CaseNoteType.GENERAL,
        nullable=False,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    noted_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        default=utc_now,
        nullable=False,
    )

    case: Mapped[Case] = relationship("Case", back_populates="notes")
    author: Mapped[User] = relationship("User")

    __table_args__ = table_args(
        Index("ix_case_notes_author_user_id", "author_user_id"),
        Index("ix_case_notes_noted_at", "noted_at"),
        Index("ix_case_notes_case_id_noted_at", "case_id", "noted_at"),
    )
