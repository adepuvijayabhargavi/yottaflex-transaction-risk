"""Registry for instantiating the six approved risk rules."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from app.models import RiskRule

from .amount import HighValueTransactionRule
from .base import BaseRiskRule
from .circular import CircularFundTransferRule
from .device import NewDeviceActivityRule
from .dormancy import DormantAccountReactivationRule
from .repeat import RepeatedTransactionsRule
from .velocity import HighTransactionVelocityRule

APPROVED_RULE_CLASSES: Final[dict[str, type[BaseRiskRule]]] = {
    "HIGH_TRANSACTION_VELOCITY": HighTransactionVelocityRule,
    "NEW_DEVICE_ACTIVITY": NewDeviceActivityRule,
    "CIRCULAR_FUND_TRANSFER": CircularFundTransferRule,
    "DORMANT_ACCOUNT_REACTIVATION": DormantAccountReactivationRule,
    "HIGH_VALUE_TRANSACTION": HighValueTransactionRule,
    "REPEATED_TRANSACTIONS": RepeatedTransactionsRule,
}

APPROVED_RULE_CODES: Final[frozenset[str]] = frozenset(APPROVED_RULE_CLASSES.keys())


def build_rule_instances(rule_models: Sequence[RiskRule]) -> list[BaseRiskRule]:
    """Instantiate the active approved risk rules from database models.

    Ignores any rule codes outside the six approved challenge rules.
    """
    instances: list[BaseRiskRule] = []
    for model in rule_models:
        if not model.is_active:
            continue
        rule_cls = APPROVED_RULE_CLASSES.get(model.code)
        if rule_cls is not None:
            instances.append(rule_cls(model))
    return instances
