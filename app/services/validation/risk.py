"""Risk-rule, assessment, finding, and alert validators."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import (
    Alert,
    RiskAssessment,
    RiskFinding,
    RiskRule,
    Transaction,
    User,
)
from app.models.enums import (
    AlertPriority,
    AlertStatus,
    AssessmentStatus,
    RiskLevel,
    RiskSeverity,
)

from .base import (
    require,
    require_enum,
    require_int_range,
    require_non_blank,
    require_reference,
    require_timestamp,
    require_timestamp_order,
)


def validate_risk_rule(
    session: Session,
    rule: RiskRule,
    *,
    record_event: bool = True,
) -> RiskRule:
    """Validate a versioned risk-rule definition."""

    entity_type = "risk_rule"
    entity_id = rule.id
    require_non_blank(
        rule.code,
        session=session,
        field="code",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_non_blank(
        rule.name,
        session=session,
        field="name",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_non_blank(
        rule.category,
        session=session,
        field="category",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_int_range(
        rule.version,
        minimum=1,
        maximum=2_147_483_647,
        session=session,
        field="version",
        entity_type=entity_type,
        entity_id=entity_id,
        code="INVALID_RULE_VERSION",
        record_event=record_event,
    )
    require_enum(
        rule.severity,
        RiskSeverity,
        session=session,
        field="severity",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_int_range(
        rule.score_weight,
        minimum=0,
        maximum=100,
        session=session,
        field="score_weight",
        entity_type=entity_type,
        entity_id=entity_id,
        code="INVALID_SCORE_WEIGHT",
        record_event=record_event,
    )
    require(
        isinstance(rule.configuration, dict),
        session=session,
        code="INVALID_CONFIGURATION",
        message="configuration must be a JSON object",
        entity_type=entity_type,
        entity_id=entity_id,
        field="configuration",
        record_event=record_event,
    )
    require_timestamp(
        rule.effective_from,
        session=session,
        field="effective_from",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_timestamp_order(
        rule.effective_from,
        rule.effective_to,
        session=session,
        earlier_field="effective_from",
        later_field="effective_to",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    return rule


def validate_risk_assessment(
    session: Session,
    assessment: RiskAssessment,
    *,
    record_event: bool = True,
) -> RiskAssessment:
    """Validate an assessment's transaction reference, score, and timing."""

    entity_type = "risk_assessment"
    entity_id = assessment.id
    transaction = require_reference(
        session,
        Transaction,
        assessment.transaction_id,
        field="transaction_id",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_non_blank(
        assessment.model_version,
        session=session,
        field="model_version",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_int_range(
        assessment.score,
        minimum=0,
        maximum=100,
        session=session,
        field="score",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_enum(
        assessment.risk_level,
        RiskLevel,
        session=session,
        field="risk_level",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_enum(
        assessment.status,
        AssessmentStatus,
        session=session,
        field="status",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_timestamp(
        assessment.assessed_at,
        session=session,
        field="assessed_at",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_timestamp_order(
        transaction.occurred_at,
        assessment.assessed_at,
        session=session,
        earlier_field="transaction.occurred_at",
        later_field="assessed_at",
        entity_type=entity_type,
        entity_id=entity_id,
        code="ASSESSMENT_BEFORE_TRANSACTION",
        record_event=record_event,
    )
    return assessment


def validate_risk_finding(
    session: Session,
    finding: RiskFinding,
    *,
    record_event: bool = True,
) -> RiskFinding:
    """Validate a finding's assessment, rule, score, and explanation."""

    entity_type = "risk_finding"
    entity_id = finding.id
    assessment = require_reference(
        session,
        RiskAssessment,
        finding.assessment_id,
        field="assessment_id",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    rule = require_reference(
        session,
        RiskRule,
        finding.rule_id,
        field="rule_id",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_non_blank(
        finding.rule_code,
        session=session,
        field="rule_code",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require(
        finding.rule_code == rule.code,
        session=session,
        code="FINDING_RULE_CODE_MISMATCH",
        message="rule_code must match the referenced risk rule",
        entity_type=entity_type,
        entity_id=entity_id,
        field="rule_code",
        details={"rule_code": finding.rule_code, "rule.code": rule.code},
        record_event=record_event,
    )
    require_int_range(
        finding.score,
        minimum=0,
        maximum=100,
        session=session,
        field="score",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_enum(
        finding.severity,
        RiskSeverity,
        session=session,
        field="severity",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_non_blank(
        finding.explanation,
        session=session,
        field="explanation",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_timestamp_order(
        assessment.assessed_at,
        finding.created_at,
        session=session,
        earlier_field="assessment.assessed_at",
        later_field="created_at",
        entity_type=entity_type,
        entity_id=entity_id,
        code="FINDING_BEFORE_ASSESSMENT",
        record_event=record_event,
    )
    return finding


def validate_alert(
    session: Session,
    alert: Alert,
    *,
    record_event: bool = True,
) -> Alert:
    """Validate alert references, consistency, score, and timestamps."""

    entity_type = "alert"
    entity_id = alert.id
    require_non_blank(
        alert.alert_reference,
        session=session,
        field="alert_reference",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require(
        alert.transaction_id is not None,
        session=session,
        code="ALERT_MISSING_TRANSACTION",
        message="An alert requires a triggering transaction",
        entity_type=entity_type,
        entity_id=entity_id,
        field="transaction_id",
        record_event=record_event,
    )
    transaction = require_reference(
        session,
        Transaction,
        alert.transaction_id,
        field="transaction_id",
        entity_type=entity_type,
        entity_id=entity_id,
        code="ALERT_TRANSACTION_NOT_FOUND",
        record_event=record_event,
    )
    assessment = require_reference(
        session,
        RiskAssessment,
        alert.assessment_id,
        field="assessment_id",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    finding = require_reference(
        session,
        RiskFinding,
        alert.finding_id,
        field="finding_id",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    rule = require_reference(
        session,
        RiskRule,
        alert.triggering_rule_id,
        field="triggering_rule_id",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_reference(
        session,
        User,
        alert.assigned_to_user_id,
        field="assigned_to_user_id",
        entity_type=entity_type,
        entity_id=entity_id,
        required=False,
        record_event=record_event,
    )
    require(
        assessment.transaction_id == transaction.id,
        session=session,
        code="ALERT_REFERENCE_MISMATCH",
        message="assessment must belong to the alert transaction",
        entity_type=entity_type,
        entity_id=entity_id,
        field="assessment_id",
        details={
            "transaction_id": transaction.id,
            "assessment_transaction_id": assessment.transaction_id,
        },
        record_event=record_event,
    )
    require(
        finding.assessment_id == assessment.id,
        session=session,
        code="ALERT_REFERENCE_MISMATCH",
        message="finding must belong to the alert assessment",
        entity_type=entity_type,
        entity_id=entity_id,
        field="finding_id",
        details={
            "assessment_id": assessment.id,
            "finding_assessment_id": finding.assessment_id,
        },
        record_event=record_event,
    )
    require(
        finding.rule_id == rule.id,
        session=session,
        code="ALERT_REFERENCE_MISMATCH",
        message="finding must belong to the triggering rule",
        entity_type=entity_type,
        entity_id=entity_id,
        field="triggering_rule_id",
        details={
            "triggering_rule_id": rule.id,
            "finding_rule_id": finding.rule_id,
        },
        record_event=record_event,
    )
    require_enum(
        alert.status,
        AlertStatus,
        session=session,
        field="status",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_enum(
        alert.priority,
        AlertPriority,
        session=session,
        field="priority",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_int_range(
        alert.score,
        minimum=0,
        maximum=100,
        session=session,
        field="score",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_non_blank(
        alert.summary,
        session=session,
        field="summary",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_timestamp_order(
        alert.created_at,
        alert.acknowledged_at,
        session=session,
        earlier_field="created_at",
        later_field="acknowledged_at",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_timestamp_order(
        alert.created_at,
        alert.closed_at,
        session=session,
        earlier_field="created_at",
        later_field="closed_at",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_timestamp_order(
        alert.acknowledged_at,
        alert.closed_at,
        session=session,
        earlier_field="acknowledged_at",
        later_field="closed_at",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_timestamp_order(
        assessment.assessed_at,
        alert.created_at,
        session=session,
        earlier_field="assessment.assessed_at",
        later_field="created_at",
        entity_type=entity_type,
        entity_id=entity_id,
        code="ALERT_BEFORE_ASSESSMENT",
        record_event=record_event,
    )
    return alert
