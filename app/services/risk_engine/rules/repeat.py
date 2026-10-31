"""Repeated transactions detection rule."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Transaction

from .base import BaseRiskRule, RuleMatch


class RepeatedTransactionsRule(BaseRiskRule):
    """Detects rapid repeated identical transactions on the same account and merchant."""

    def evaluate(self, session: Session, transaction: Transaction) -> RuleMatch | None:
        if transaction.debit_account_id is None:
            return None

        repeat_count = int(self.configuration.get("repeat_count", 3))
        window_minutes = int(self.configuration.get("window_minutes", 30))
        delta = timedelta(minutes=window_minutes)

        start_time = transaction.occurred_at - delta
        end_time = transaction.occurred_at + delta

        stmt = (
            select(Transaction)
            .where(
                Transaction.debit_account_id == transaction.debit_account_id,
                Transaction.merchant_id == transaction.merchant_id,
                Transaction.amount == transaction.amount,
                Transaction.occurred_at >= start_time,
                Transaction.occurred_at <= end_time,
            )
            .order_by(Transaction.occurred_at.asc(), Transaction.id.asc())
        )
        candidates = list(session.scalars(stmt))
        n = len(candidates)
        if n < repeat_count:
            return None

        target_indices = [
            i for i, cand in enumerate(candidates) if cand.id == transaction.id
        ]
        target_idx = (
            target_indices[0]
            if target_indices
            else next(
                (
                    i
                    for i, cand in enumerate(candidates)
                    if cand.transaction_reference == transaction.transaction_reference
                ),
                None,
            )
        )
        if target_idx is None:
            target_idx = 0
            for i, cand in enumerate(candidates):
                if cand.occurred_at >= transaction.occurred_at:
                    target_idx = i
                    break

        best_cluster: list[Transaction] = []
        left = 0
        for right in range(n):
            while candidates[right].occurred_at - candidates[left].occurred_at > delta:
                left += 1
            count = right - left + 1
            if (
                count >= repeat_count
                and left <= target_idx <= right
                and count > len(best_cluster)
            ):
                best_cluster = candidates[left : right + 1]

        if len(best_cluster) >= repeat_count:
            count = len(best_cluster)
            evidence: dict[str, Any] = {
                "debit_account_id": transaction.debit_account_id,
                "merchant_id": transaction.merchant_id,
                "amount": str(transaction.amount),
                "repeat_count": count,
                "threshold": repeat_count,
                "window_minutes": window_minutes,
                "cluster_transaction_references": [
                    t.transaction_reference for t in best_cluster
                ],
            }
            explanation = (
                f"Repeated transactions: {count} identical transactions of "
                f"{transaction.amount:,.2f} on the same account within {window_minutes} "
                f"minutes (threshold: {repeat_count})"
            )
            return RuleMatch(
                rule_code=self.code,
                score=self.weight,
                severity=self.severity,
                explanation=explanation,
                evidence=evidence,
            )

        return None
