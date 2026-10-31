"""Dormant account reactivation detection rule."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, Transaction
from app.models.enums import AccountStatus

from .base import BaseRiskRule, RuleMatch


class DormantAccountReactivationRule(BaseRiskRule):
    """Detects transactions on accounts that were dormant or prolonged inactive."""

    def evaluate(self, session: Session, transaction: Transaction) -> RuleMatch | None:
        if transaction.debit_account_id is None:
            return None

        dormant_days = int(self.configuration.get("dormant_days", 90))
        dormant_delta = timedelta(days=dormant_days)

        is_dormant_snapshot = (
            transaction.debit_account_status_snapshot == AccountStatus.DORMANT
        )

        # Check previous transaction on this debit account
        stmt = (
            select(Transaction.occurred_at)
            .where(
                Transaction.debit_account_id == transaction.debit_account_id,
                Transaction.occurred_at < transaction.occurred_at,
            )
            .order_by(Transaction.occurred_at.desc())
            .limit(1)
        )
        prev_occurred_at = session.scalar(stmt)

        days_inactive: int | None = None
        is_inactive_prolonged = False

        if prev_occurred_at is not None:
            inactivity = transaction.occurred_at - prev_occurred_at
            days_inactive = inactivity.days
            if inactivity >= dormant_delta:
                is_inactive_prolonged = True
        else:
            # Check account opened date if no previous transaction
            account = (
                transaction.debit_account
                if getattr(transaction, "debit_account", None) is not None
                else session.get(Account, transaction.debit_account_id)
            )
            if account and account.opened_at:
                inactivity = transaction.occurred_at - account.opened_at
                days_inactive = inactivity.days
                if inactivity >= dormant_delta:
                    is_inactive_prolonged = True

        if is_dormant_snapshot or is_inactive_prolonged:
            reason = []
            if is_dormant_snapshot:
                reason.append("account status marked DORMANT")
            if is_inactive_prolonged:
                reason.append(
                    f"{days_inactive} days of inactivity exceeding {dormant_days}-day threshold"
                )

            evidence: dict[str, Any] = {
                "debit_account_id": transaction.debit_account_id,
                "snapshot_status": (
                    transaction.debit_account_status_snapshot.value
                    if transaction.debit_account_status_snapshot
                    else None
                ),
                "dormant_days_threshold": dormant_days,
                "days_inactive": days_inactive,
                "is_dormant_snapshot": is_dormant_snapshot,
                "is_inactive_prolonged": is_inactive_prolonged,
            }
            explanation = (
                "Dormant account reactivation: transaction occurred while "
                + " and ".join(reason)
            )
            return RuleMatch(
                rule_code=self.code,
                score=self.weight,
                severity=self.severity,
                explanation=explanation,
                evidence=evidence,
            )

        return None
