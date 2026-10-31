"""Alert generation service for risky transactions."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from app.models import Alert, RiskAssessment, RiskFinding
from app.models.enums import AlertPriority, AlertStatus, RiskSeverity

SEVERITY_RANK: dict[RiskSeverity, int] = {
    RiskSeverity.LOW: 1,
    RiskSeverity.MEDIUM: 2,
    RiskSeverity.HIGH: 3,
    RiskSeverity.CRITICAL: 4,
}


def should_generate_alert(
    assessment: RiskAssessment,
    findings: Sequence[RiskFinding],
    threshold: int,
) -> bool:
    """Determine whether an alert should be created for this assessment.

    Alert is triggered when:
    - Composite score >= threshold; OR
    - Any triggered finding has CRITICAL severity.
    """
    if assessment.score >= threshold:
        return True
    return any(f.severity == RiskSeverity.CRITICAL for f in findings)


def select_primary_finding(findings: Sequence[RiskFinding]) -> RiskFinding | None:
    """Select the primary triggering finding (highest severity, then highest score)."""
    if not findings:
        return None
    return max(
        findings,
        key=lambda f: (SEVERITY_RANK.get(f.severity, 0), f.score),
    )


class AlertGenerator:
    """Generates Alert records for qualifying risk assessments."""

    def __init__(self, default_threshold: int = 40) -> None:
        self.default_threshold = default_threshold

    def generate_alert(
        self,
        assessment: RiskAssessment,
        findings: Sequence[RiskFinding],
        threshold: int | None = None,
    ) -> Alert | None:
        """Create an Alert if the assessment qualifies, or return None."""
        effective_threshold = (
            threshold if threshold is not None else self.default_threshold
        )
        if not should_generate_alert(assessment, findings, effective_threshold):
            return None

        primary = select_primary_finding(findings)
        if primary is None:
            return None

        # Build stable, unique alert reference within 40 characters
        # e.g., ALT-v1.0.0-00000123
        clean_version = assessment.model_version.replace(" ", "-")[:12]
        alert_ref = f"ALT-{clean_version}-{assessment.transaction_id:08d}"

        priority_val = AlertPriority(assessment.risk_level.value)
        summary = (
            f"Risk alert: {primary.rule_code} (Score: {assessment.score}, "
            f"Level: {assessment.risk_level.value})"
        )
        details: dict[str, Any] = {
            "triggering_rule_code": primary.rule_code,
            "findings_count": len(findings),
            "effective_threshold": effective_threshold,
            "evidence": primary.evidence,
        }

        created_at = assessment.assessed_at + timedelta(seconds=1)

        alert = Alert(
            alert_reference=alert_ref,
            transaction_id=assessment.transaction_id,
            assessment_id=assessment.id,
            finding_id=primary.id,
            triggering_rule_id=primary.rule_id,
            status=AlertStatus.OPEN,
            priority=priority_val,
            score=assessment.score,
            summary=summary,
            details=details,
            created_at=created_at,
            updated_at=created_at,
        )
        return alert
