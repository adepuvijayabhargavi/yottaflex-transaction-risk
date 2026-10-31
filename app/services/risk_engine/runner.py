"""Execution runner for batch transaction risk scoring and alerting."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.database import DatabaseRole, database_url_for_role
from app.models import (
    Alert,
    RiskAssessment,
    RiskFinding,
    RiskRule,
    Transaction,
)
from app.models.enums import AlertPriority, RiskLevel

from .alerting import AlertGenerator
from .evaluator import TransactionEvaluator
from .rules.registry import APPROVED_RULE_CODES, build_rule_instances

logger = logging.getLogger(__name__)


@dataclass
class RiskEvaluationSummary:
    """Summary of a completed risk evaluation run."""

    model_version: str
    effective_threshold: int
    total_transactions: int = 0
    assessed_count: int = 0
    skipped_count: int = 0
    findings_count: int = 0
    alerts_count: int = 0
    risk_level_counts: dict[str, int] = field(default_factory=dict)
    priority_counts: dict[str, int] = field(default_factory=dict)
    rule_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_version": self.model_version,
            "effective_threshold": self.effective_threshold,
            "total_transactions": self.total_transactions,
            "assessed_count": self.assessed_count,
            "skipped_count": self.skipped_count,
            "findings_count": self.findings_count,
            "alerts_count": self.alerts_count,
            "risk_level_counts": self.risk_level_counts,
            "priority_counts": self.priority_counts,
            "rule_counts": self.rule_counts,
        }


def get_risk_session_factory() -> sessionmaker[Session]:
    """Create a sessionmaker using only YTF_RISK_DATABASE_URL."""
    url = database_url_for_role(DatabaseRole.RISK)
    assert url is not None
    engine = create_engine(url, pool_pre_ping=True)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def evaluate_transaction(
    session: Session,
    transaction: Transaction,
    evaluator: TransactionEvaluator,
    alert_generator: AlertGenerator,
    model_version: str,
    threshold: int | None = None,
) -> tuple[RiskAssessment | None, list[RiskFinding], Alert | None]:
    """Evaluate a single transaction with rerun idempotency."""
    # Idempotency check: see if assessment already exists
    existing = session.scalar(
        select(RiskAssessment.id).where(
            RiskAssessment.transaction_id == transaction.id,
            RiskAssessment.model_version == model_version,
        )
    )
    if existing is not None:
        return None, [], None

    assessment, findings = evaluator.evaluate(session, transaction, model_version)
    session.add(assessment)
    session.flush()

    for finding in findings:
        finding.assessment_id = assessment.id
        session.add(finding)
    session.flush()

    alert = alert_generator.generate_alert(assessment, findings, threshold=threshold)
    if alert is not None:
        session.add(alert)
        session.flush()

    return assessment, findings, alert


def run_risk_evaluation(
    model_version: str = "v1.0.0",
    threshold: int | None = None,
    batch_size: int = 100,
    session_factory: sessionmaker[Session] | None = None,
    default_threshold: int = 40,
) -> RiskEvaluationSummary:
    """Run batch risk evaluation across all transactions with complete idempotency."""
    effective_threshold = threshold if threshold is not None else default_threshold
    summary = RiskEvaluationSummary(
        model_version=model_version,
        effective_threshold=effective_threshold,
        risk_level_counts={lvl.value: 0 for lvl in RiskLevel},
        priority_counts={pri.value: 0 for pri in AlertPriority},
    )

    factory = session_factory or get_risk_session_factory()

    with factory() as session:
        # Load active approved risk rules from database
        stmt_rules = (
            select(RiskRule)
            .where(
                RiskRule.is_active.is_(True),
                RiskRule.code.in_(APPROVED_RULE_CODES),
            )
            .order_by(RiskRule.id.asc())
        )
        rule_models = list(session.scalars(stmt_rules))
        rules = build_rule_instances(rule_models)
        evaluator = TransactionEvaluator(rules)
        alert_generator = AlertGenerator(default_threshold=default_threshold)

        # Query all transactions in chronological order
        stmt_tx = select(Transaction).order_by(
            Transaction.occurred_at.asc(), Transaction.id.asc()
        )
        transactions = list(session.scalars(stmt_tx))
        summary.total_transactions = len(transactions)

        # Process in batches
        for i in range(0, len(transactions), batch_size):
            batch = transactions[i : i + batch_size]
            for tx in batch:
                try:
                    assessment, findings, alert = evaluate_transaction(
                        session=session,
                        transaction=tx,
                        evaluator=evaluator,
                        alert_generator=alert_generator,
                        model_version=model_version,
                        threshold=threshold,
                    )
                    if assessment is None:
                        summary.skipped_count += 1
                        continue

                    summary.assessed_count += 1
                    summary.risk_level_counts[assessment.risk_level.value] = (
                        summary.risk_level_counts.get(assessment.risk_level.value, 0)
                        + 1
                    )
                    summary.findings_count += len(findings)

                    for f in findings:
                        summary.rule_counts[f.rule_code] = (
                            summary.rule_counts.get(f.rule_code, 0) + 1
                        )

                    if alert is not None:
                        summary.alerts_count += 1
                        summary.priority_counts[alert.priority.value] = (
                            summary.priority_counts.get(alert.priority.value, 0) + 1
                        )

                except IntegrityError as exc:
                    session.rollback()
                    logger.warning(
                        "Integrity collision for transaction %s; skipping. %s",
                        tx.id,
                        exc,
                    )
                    summary.skipped_count += 1

            session.commit()

    return summary
