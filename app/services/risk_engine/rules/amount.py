"""High-value transaction detection rule."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models import Transaction

from .base import BaseRiskRule, RuleMatch


class HighValueTransactionRule(BaseRiskRule):
    """Detects transactions exceeding fixed high monetary value thresholds."""

    def evaluate(self, session: Session, transaction: Transaction) -> RuleMatch | None:
        amount_threshold = Decimal(
            str(self.configuration.get("amount_threshold", 50000))
        )
        currency_filter = self.configuration.get("currency")

        if currency_filter:
            tx_currency = (
                transaction.currency.value
                if hasattr(transaction.currency, "value")
                else str(transaction.currency)
            )
            if tx_currency != currency_filter:
                return None

        if transaction.amount >= amount_threshold:
            currency_str = (
                transaction.currency.value
                if hasattr(transaction.currency, "value")
                else str(transaction.currency)
            )
            evidence: dict[str, Any] = {
                "amount": str(transaction.amount),
                "threshold": str(amount_threshold),
                "currency": currency_str,
            }
            explanation = (
                f"High-value transaction: amount {currency_str} {transaction.amount:,.2f} "
                f"meets or exceeds threshold of {currency_str} {amount_threshold:,.2f}"
            )
            return RuleMatch(
                rule_code=self.code,
                score=self.weight,
                severity=self.severity,
                explanation=explanation,
                evidence=evidence,
            )

        return None
