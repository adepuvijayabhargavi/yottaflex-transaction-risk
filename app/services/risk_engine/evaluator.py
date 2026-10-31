"""Transaction risk evaluation and composite scoring engine."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models import RiskAssessment, RiskFinding, Transaction
from app.models.enums import AssessmentStatus, RiskLevel, RiskSeverity

from .rules.base import BaseRiskRule


def determine_risk_level(
    composite_score: int,
    findings: Sequence[RiskFinding],
) -> RiskLevel:
    """Classify the risk level using the approved tiers and critical elevation.

    - CRITICAL: Score >= 80 OR at least one finding has CRITICAL severity.
    - HIGH: 60 <= Score < 80 (and no critical finding).
    - MEDIUM: 40 <= Score < 60 (and no critical finding).
    - LOW: 0 <= Score < 40 (and no critical finding).
    """
    has_critical_finding = any(
        finding.severity == RiskSeverity.CRITICAL for finding in findings
    )
    if has_critical_finding or composite_score >= 80:
        return RiskLevel.CRITICAL
    if composite_score >= 60:
        return RiskLevel.HIGH
    if composite_score >= 40:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


class TransactionEvaluator:
    """Evaluates transactions against active risk rules and calculates scores."""

    def __init__(self, rules: Sequence[BaseRiskRule]) -> None:
        self.rules = list(rules)

    def evaluate(
        self,
        session: Session,
        transaction: Transaction,
        model_version: str,
    ) -> tuple[RiskAssessment, list[RiskFinding]]:
        """Evaluate a transaction and return its RiskAssessment and RiskFindings."""
        findings: list[RiskFinding] = []
        assessed_time = transaction.occurred_at + timedelta(seconds=1)

        for rule in self.rules:
            match = rule.evaluate(session, transaction)
            if match is not None:
                finding = RiskFinding(
                    rule_id=rule.rule_model.id,
                    rule_code=match.rule_code,
                    score=match.score,
                    severity=match.severity,
                    explanation=match.explanation,
                    evidence=match.evidence,
                    created_at=assessed_time,
                )
                findings.append(finding)

        composite_score = min(sum(f.score for f in findings), 100)
        risk_level = determine_risk_level(composite_score, findings)

        explanation_data: dict[str, Any] = {
            "score": composite_score,
            "risk_level": risk_level.value,
            "findings_count": len(findings),
            "triggered_rules": [f.rule_code for f in findings],
            "rule_weights": {f.rule_code: f.score for f in findings},
        }

        assessment = RiskAssessment(
            transaction_id=transaction.id,
            model_version=model_version,
            score=composite_score,
            risk_level=risk_level,
            status=AssessmentStatus.COMPLETED,
            assessed_at=assessed_time,
            explanation=explanation_data,
        )

        return assessment, findings
