"""Base interfaces for risk detection rules."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.models import RiskRule, Transaction
from app.models.enums import RiskSeverity


@dataclass(frozen=True, slots=True)
class RuleMatch:
    """An explainable match produced by a risk detection rule."""

    rule_code: str
    score: int
    severity: RiskSeverity
    explanation: str
    evidence: dict[str, Any]


class BaseRiskRule(ABC):
    """Abstract base class for all risk detection rules."""

    rule_model: RiskRule
    code: str
    weight: int
    severity: RiskSeverity
    configuration: dict[str, Any]

    def __init__(self, rule_model: RiskRule) -> None:
        self.rule_model = rule_model
        self.code = rule_model.code
        self.weight = rule_model.score_weight
        self.severity = rule_model.severity
        self.configuration = rule_model.configuration or {}

    @abstractmethod
    def evaluate(self, session: Session, transaction: Transaction) -> RuleMatch | None:
        """Evaluate a transaction and return a RuleMatch if triggered."""
