"""Circular fund transfer detection rule."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Transaction
from app.models.enums import TransactionType

from .base import BaseRiskRule, RuleMatch


class CircularFundTransferRule(BaseRiskRule):
    """Detects transfer cycles passing funds through a loop of accounts."""

    def evaluate(self, session: Session, transaction: Transaction) -> RuleMatch | None:
        if (
            transaction.debit_account_id is None
            or transaction.credit_account_id is None
        ):
            return None

        window_hours = float(self.configuration.get("window_hours", 24))
        max_cycle_length = int(self.configuration.get("max_cycle_length", 4))
        max_delta = timedelta(hours=window_hours)

        # 1. First check within the same transfer group if present
        candidates: list[Transaction] = []
        if transaction.transfer_group_id is not None:
            stmt = select(Transaction).where(
                Transaction.transfer_group_id == transaction.transfer_group_id,
                Transaction.debit_account_id.is_not(None),
                Transaction.credit_account_id.is_not(None),
            )
            candidates = list(session.scalars(stmt))

        # 2. If not found in transfer group or no transfer group, check broader window
        cycle = self._find_cycle(candidates, transaction, max_cycle_length, max_delta)
        if not cycle:
            # Query internal/transfer transactions around transaction.occurred_at
            start_time = transaction.occurred_at - max_delta
            end_time = transaction.occurred_at + max_delta
            stmt = select(Transaction).where(
                Transaction.occurred_at >= start_time,
                Transaction.occurred_at <= end_time,
                Transaction.debit_account_id.is_not(None),
                Transaction.credit_account_id.is_not(None),
                Transaction.transaction_type == TransactionType.INTERNAL,
            )
            broader_candidates = list(session.scalars(stmt))
            cycle = self._find_cycle(
                broader_candidates, transaction, max_cycle_length, max_delta
            )

        if cycle:
            cycle_accounts, cycle_txns = cycle
            timestamps = [t.occurred_at for t in cycle_txns]
            duration = max(timestamps) - min(timestamps)
            duration_hours = round(duration.total_seconds() / 3600, 2)
            cycle_str = " -> ".join(str(acc) for acc in cycle_accounts)

            evidence: dict[str, Any] = {
                "transfer_group_id": transaction.transfer_group_id,
                "cycle_accounts": cycle_accounts,
                "cycle_length": len(cycle_accounts) - 1,
                "max_cycle_length": max_cycle_length,
                "duration_hours": duration_hours,
                "window_hours": window_hours,
                "cycle_transaction_references": [
                    t.transaction_reference for t in cycle_txns
                ],
            }
            explanation = (
                f"Circular fund transfer detected: {cycle_str} across "
                f"{len(cycle_accounts) - 1} accounts within {duration_hours} hours "
                f"(window: {window_hours} hours)"
            )
            return RuleMatch(
                rule_code=self.code,
                score=self.weight,
                severity=self.severity,
                explanation=explanation,
                evidence=evidence,
            )

        return None

    def _find_cycle(
        self,
        transactions: list[Transaction],
        target_tx: Transaction,
        max_length: int,
        max_delta: timedelta,
    ) -> tuple[list[int], list[Transaction]] | None:
        """Find a directed cycle containing target_tx within max_length and max_delta."""
        if not transactions:
            return None

        # Build adjacency graph: src -> list of (dst, transaction)
        adj: dict[int, list[tuple[int, Transaction]]] = {}
        for tx in transactions:
            if tx.debit_account_id and tx.credit_account_id:
                adj.setdefault(tx.debit_account_id, []).append(
                    (tx.credit_account_id, tx)
                )

        target_src = target_tx.debit_account_id
        target_dst = target_tx.credit_account_id
        if target_src is None or target_dst is None:
            return None

        # Search for path from target_dst back to target_src
        # Path length (number of hops from target_dst to target_src) <= max_length - 1
        visited: set[int] = {target_dst}
        path_nodes: list[int] = [target_dst]
        path_txs: list[Transaction] = [target_tx]

        def dfs(current: int, depth: int) -> tuple[list[int], list[Transaction]] | None:
            if current == target_src:
                return (
                    [target_src] + path_nodes,
                    list(path_txs),
                )
            if depth >= max_length:
                return None

            for nxt, tx in adj.get(current, []):
                # Verify time difference
                times = [t.occurred_at for t in path_txs] + [tx.occurred_at]
                if max(times) - min(times) > max_delta:
                    continue

                if nxt == target_src or nxt not in visited:
                    visited.add(nxt)
                    path_nodes.append(nxt)
                    path_txs.append(tx)
                    result = dfs(nxt, depth + 1)
                    if result:
                        return result
                    path_txs.pop()
                    path_nodes.pop()
                    visited.remove(nxt)
            return None

        return dfs(target_dst, 1)
