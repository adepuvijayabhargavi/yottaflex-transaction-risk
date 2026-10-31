"""Explainable transaction risk scoring engine and alert generation."""

from .alerting import AlertGenerator, select_primary_finding, should_generate_alert
from .evaluator import TransactionEvaluator, determine_risk_level
from .rules import (
    APPROVED_RULE_CLASSES,
    APPROVED_RULE_CODES,
    BaseRiskRule,
    CircularFundTransferRule,
    DormantAccountReactivationRule,
    HighTransactionVelocityRule,
    HighValueTransactionRule,
    NewDeviceActivityRule,
    RepeatedTransactionsRule,
    RuleMatch,
    build_rule_instances,
)
from .runner import (
    RiskEvaluationSummary,
    evaluate_transaction,
    get_risk_session_factory,
    run_risk_evaluation,
)

__all__ = [
    "APPROVED_RULE_CLASSES",
    "APPROVED_RULE_CODES",
    "AlertGenerator",
    "BaseRiskRule",
    "CircularFundTransferRule",
    "DormantAccountReactivationRule",
    "HighTransactionVelocityRule",
    "HighValueTransactionRule",
    "NewDeviceActivityRule",
    "RepeatedTransactionsRule",
    "RiskEvaluationSummary",
    "RuleMatch",
    "TransactionEvaluator",
    "build_rule_instances",
    "determine_risk_level",
    "evaluate_transaction",
    "get_risk_session_factory",
    "run_risk_evaluation",
    "select_primary_finding",
    "should_generate_alert",
]
