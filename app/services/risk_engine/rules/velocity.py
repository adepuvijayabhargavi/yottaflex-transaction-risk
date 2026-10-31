"""High transaction velocity detection rule."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Transaction
from app.models.enums import TransactionType

from .base import BaseRiskRule, RuleMatch


class HighTransactionVelocityRule(BaseRiskRule):
    """Detects rapid bursts of transactions on the same debit account."""

    def evaluate(self, session: Session, transaction: Transaction) -> RuleMatch | None:
        if transaction.debit_account_id is None:
            return None

        threshold = int(self.configuration.get("transaction_count", 4))
        window_minutes = int(self.configuration.get("window_minutes", 60))
        delta = timedelta(minutes=window_minutes)

        start_time = transaction.occurred_at - delta
        end_time = transaction.occurred_at + delta

        stmt = (
            select(Transaction)
            .where(
                Transaction.debit_account_id == transaction.debit_account_id,
                Transaction.occurred_at >= start_time,
                Transaction.occurred_at <= end_time,
                Transaction.transaction_type.in_(
                    [TransactionType.OUTGOING, TransactionType.INTERNAL]
                ),
            )
            .order_by(Transaction.occurred_at.asc(), Transaction.id.asc())
        )
        candidates = list(session.scalars(stmt))

        # Check if the current transaction is part of any sliding window <= window_minutes
        # containing at least threshold transactions.
        n = len(candidates)
        if n < threshold:
            return None

        # Find candidate index
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
            # Fallback if unpersisted transaction
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
            # Window [left, right] is within delta
            count = right - left + 1
            if (
                count >= threshold
                and left <= target_idx <= right
                and count > len(best_cluster)
            ):
                best_cluster = candidates[left : right + 1]

        if len(best_cluster) >= threshold:
            count = len(best_cluster)
            evidence: dict[str, Any] = {
                "debit_account_id": transaction.debit_account_id,
                "transaction_count": count,
                "threshold": threshold,
                "window_minutes": window_minutes,
                "cluster_transaction_references": [
                    t.transaction_reference for t in best_cluster
                ],
            }
            explanation = (
                f"High transaction velocity: {count} transactions on account within "
                f"{window_minutes} minutes (threshold: {threshold})"
            )
            return RuleMatch(
                rule_code=self.code,
                score=self.weight,
                severity=self.severity,
                explanation=explanation,
                evidence=evidence,
            )

        return None
