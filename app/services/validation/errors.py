"""Validation issue and exception types."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """A single machine-readable validation failure."""

    code: str
    message: str
    entity_type: str
    entity_id: int | None = None
    field: str | None = None
    details: dict[str, Any] = dataclass_field(default_factory=dict)


class ValidationError(ValueError):
    """Raised when an input fails a documented validation rule."""

    def __init__(self, issue: ValidationIssue) -> None:
        self.issue = issue
        super().__init__(issue.message)
