"""Unit tests for risk evaluation, composite scoring, risk level mapping, and alerting."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from app.models import RiskAssessment, RiskFinding, Transaction
from app.models.enums import (
    AlertPriority,
    AlertStatus,
    AssessmentStatus,
    RiskLevel,
    RiskSeverity,
)
from app.services.risk_engine.alerting import (
    AlertGenerator,
    select_primary_finding,
    should_generate_alert,
)
from app.services.risk_engine.evaluator import (
    TransactionEvaluator,
    determine_risk_level,
)
from app.services.risk_engine.rules.base import RuleMatch

BASE_TIME = datetime(2026, 10, 20, 12, 0, 0)


def _mock_finding(
    score: int,
    severity: RiskSeverity,
    code: str = "TEST_RULE",
    id_: int = 1,
    rule_id: int = 10,
) -> RiskFinding:
    f = RiskFinding(
        assessment_id=1,
        rule_id=rule_id,
        rule_code=code,
        score=score,
        severity=severity,
        explanation="Test finding",
        evidence={},
        created_at=BASE_TIME,
    )
    f.id = id_
    return f


def test_determine_risk_level_tiers():
    # LOW: 0 - 39
    assert determine_risk_level(0, []) == RiskLevel.LOW
    assert (
        determine_risk_level(39, [_mock_finding(39, RiskSeverity.LOW)]) == RiskLevel.LOW
    )

    # MEDIUM: 40 - 59
    assert (
        determine_risk_level(40, [_mock_finding(40, RiskSeverity.MEDIUM)])
        == RiskLevel.MEDIUM
    )
    assert (
        determine_risk_level(59, [_mock_finding(59, RiskSeverity.MEDIUM)])
        == RiskLevel.MEDIUM
    )

    # HIGH: 60 - 79
    assert (
        determine_risk_level(60, [_mock_finding(60, RiskSeverity.HIGH)])
        == RiskLevel.HIGH
    )
    assert (
        determine_risk_level(79, [_mock_finding(79, RiskSeverity.HIGH)])
        == RiskLevel.HIGH
    )

    # CRITICAL: 80 - 100
    assert (
        determine_risk_level(80, [_mock_finding(80, RiskSeverity.HIGH)])
        == RiskLevel.CRITICAL
    )
    assert (
        determine_risk_level(100, [_mock_finding(100, RiskSeverity.HIGH)])
        == RiskLevel.CRITICAL
    )


def test_determine_risk_level_critical_elevation():
    # Any finding with CRITICAL severity elevates risk_level to CRITICAL, even if score < 80
    critical_finding = _mock_finding(
        30, RiskSeverity.CRITICAL, "CIRCULAR_FUND_TRANSFER"
    )
    assert determine_risk_level(30, [critical_finding]) == RiskLevel.CRITICAL
    assert determine_risk_level(0, [critical_finding]) == RiskLevel.CRITICAL


def test_evaluator_composite_score_capped_at_100():
    rule1 = MagicMock()
    rule1.rule_model = MagicMock(id=1)
    rule1.code = "RULE_1"
    rule1.evaluate.return_value = RuleMatch("RULE_1", 60, RiskSeverity.HIGH, "exp1", {})

    rule2 = MagicMock()
    rule2.rule_model = MagicMock(id=2)
    rule2.code = "RULE_2"
    rule2.evaluate.return_value = RuleMatch("RULE_2", 60, RiskSeverity.HIGH, "exp2", {})

    evaluator = TransactionEvaluator([rule1, rule2])

    tx = MagicMock(spec=Transaction)
    tx.id = 100
    tx.occurred_at = BASE_TIME

    assessment, findings = evaluator.evaluate(MagicMock(), tx, "v1.0.0")

    assert len(findings) == 2
    # 60 + 60 = 120, capped at 100
    assert assessment.score == 100
    assert assessment.risk_level == RiskLevel.CRITICAL
    assert assessment.status == AssessmentStatus.COMPLETED


def test_alert_generator_conditions():
    gen = AlertGenerator(default_threshold=40)

    # 1. Below threshold, no critical finding -> No alert
    tx = MagicMock(spec=Transaction)
    tx.id = 101

    ass_low = RiskAssessment(
        transaction_id=101,
        model_version="v1.0.0",
        score=20,
        risk_level=RiskLevel.LOW,
        assessed_at=BASE_TIME,
    )
    ass_low.id = 1
    f_low = _mock_finding(20, RiskSeverity.HIGH, "HIGH_VALUE_TRANSACTION", id_=1)

    assert not should_generate_alert(ass_low, [f_low], threshold=40)
    assert gen.generate_alert(ass_low, [f_low]) is None

    # 2. Meets threshold (score >= 40) -> Alert generated
    ass_med = RiskAssessment(
        transaction_id=102,
        model_version="v1.0.0",
        score=40,
        risk_level=RiskLevel.MEDIUM,
        assessed_at=BASE_TIME,
    )
    ass_med.id = 2
    f_med = _mock_finding(40, RiskSeverity.HIGH, "HIGH_TRANSACTION_VELOCITY", id_=2)

    assert should_generate_alert(ass_med, [f_med], threshold=40)
    alert = gen.generate_alert(ass_med, [f_med])
    assert alert is not None
    assert alert.transaction_id == 102
    assert alert.finding_id == 2
    assert alert.score == 40
    assert alert.priority == AlertPriority.MEDIUM
    assert alert.status == AlertStatus.OPEN
    assert alert.alert_reference == "ALT-v1.0.0-00000102"
    assert len(alert.alert_reference) <= 40

    # 3. Score below threshold, but finding is CRITICAL -> Alert generated!
    ass_crit = RiskAssessment(
        transaction_id=103,
        model_version="v1.0.0",
        score=30,
        risk_level=RiskLevel.CRITICAL,
        assessed_at=BASE_TIME,
    )
    ass_crit.id = 3
    f_crit = _mock_finding(30, RiskSeverity.CRITICAL, "CIRCULAR_FUND_TRANSFER", id_=3)

    assert should_generate_alert(ass_crit, [f_crit], threshold=40)
    alert_crit = gen.generate_alert(ass_crit, [f_crit])
    assert alert_crit is not None
    assert alert_crit.priority == AlertPriority.CRITICAL
    assert alert_crit.finding_id == 3

    # 4. Optional CLI threshold override (e.g. threshold = 15)
    assert should_generate_alert(ass_low, [f_low], threshold=15)
    alert_override = gen.generate_alert(ass_low, [f_low], threshold=15)
    assert alert_override is not None
    assert alert_override.score == 20


def test_select_primary_finding_ordering():
    # Priority order: CRITICAL > HIGH > MEDIUM > LOW, then score descending
    f_low = _mock_finding(10, RiskSeverity.LOW, "RULE_LOW")
    f_med = _mock_finding(20, RiskSeverity.MEDIUM, "RULE_MED")
    f_high = _mock_finding(20, RiskSeverity.HIGH, "RULE_HIGH")
    f_crit = _mock_finding(30, RiskSeverity.CRITICAL, "RULE_CRIT")

    # Critical wins even if another rule has equal/higher score
    assert select_primary_finding([f_low, f_med, f_high, f_crit]) == f_crit
    assert select_primary_finding([f_low, f_med, f_high]) == f_high
    assert select_primary_finding([]) is None
