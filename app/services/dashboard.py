"""Dashboard statistics and risk indicators aggregation service."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models import (
    Account,
    Alert,
    Case,
    RiskAssessment,
    RiskRule,
    Transaction,
)
from app.models.enums import AlertPriority, AlertStatus, CaseStatus, RiskLevel

DEFAULT_MODEL_VERSION = "v1.0.1"
RECENT_ALERT_SCAN_LIMIT = 50
RECENT_ALERT_DISPLAY_LIMIT = 10


def _model_version_filter(model_version: str):
    """Return the assessment filter used by version-scoped dashboard metrics."""

    return RiskAssessment.model_version == model_version


def get_dashboard_stats(
    session: Session,
    *,
    model_version: str = DEFAULT_MODEL_VERSION,
    reference_date: str | None = None,
    alert_threshold: int | None = None,
) -> dict[str, Any]:
    """Calculate operational KPIs and risk indicators for one model version."""

    version_filter = _model_version_filter(model_version)

    # 1. Core KPIs. Transactions and cases are version-independent, while
    # alerts are scoped to the selected assessment model version.
    total_transactions = session.scalar(select(func.count(Transaction.id))) or 0
    total_alerts = (
        session.scalar(
            select(func.count(Alert.id))
            .join(RiskAssessment, Alert.assessment_id == RiskAssessment.id)
            .where(version_filter)
        )
        or 0
    )
    open_alerts = (
        session.scalar(
            select(func.count(Alert.id))
            .join(RiskAssessment, Alert.assessment_id == RiskAssessment.id)
            .where(version_filter, Alert.status == AlertStatus.OPEN)
        )
        or 0
    )
    pending_cases = (
        session.scalar(
            select(func.count(Case.id)).where(
                Case.status.in_([CaseStatus.OPEN, CaseStatus.IN_REVIEW])
            )
        )
        or 0
    )
    escalated_cases = (
        session.scalar(
            select(func.count(Case.id)).where(Case.status == CaseStatus.ESCALATED)
        )
        or 0
    )
    closed_cases = (
        session.scalar(
            select(func.count(Case.id)).where(Case.status == CaseStatus.CLOSED)
        )
        or 0
    )

    kpis = {
        "total_transactions": total_transactions,
        "total_alerts": total_alerts,
        "open_alerts": open_alerts,
        "pending_cases": pending_cases,
        "escalated_cases": escalated_cases,
        "closed_cases": closed_cases,
    }

    # 2. Risk Distribution (from RiskAssessment for the selected model version)
    risk_level_rows = session.execute(
        select(RiskAssessment.risk_level, func.count(RiskAssessment.id))
        .where(version_filter)
        .group_by(RiskAssessment.risk_level)
    ).all()
    risk_distribution = {
        r[0].value if hasattr(r[0], "value") else str(r[0]): r[1]
        for r in risk_level_rows
    }
    for level in RiskLevel:
        risk_distribution.setdefault(level.value, 0)

    total_assessments = sum(risk_distribution.values())
    risk_distribution_percentages = {
        level: (
            round((count / total_assessments) * 100, 1) if total_assessments else 0.0
        )
        for level, count in risk_distribution.items()
    }

    # 3. Alert Priority Breakdown (scoped to the selected model version)
    alert_priority_rows = session.execute(
        select(Alert.priority, func.count(Alert.id))
        .join(RiskAssessment, Alert.assessment_id == RiskAssessment.id)
        .where(version_filter)
        .group_by(Alert.priority)
    ).all()
    alert_priorities = {
        r[0].value if hasattr(r[0], "value") else str(r[0]): r[1]
        for r in alert_priority_rows
    }
    for priority in AlertPriority:
        alert_priorities.setdefault(priority.value, 0)

    # Alert Status Breakdown (scoped to the selected model version)
    alert_status_rows = session.execute(
        select(Alert.status, func.count(Alert.id))
        .join(RiskAssessment, Alert.assessment_id == RiskAssessment.id)
        .where(version_filter)
        .group_by(Alert.status)
    ).all()
    alert_statuses = {
        r[0].value if hasattr(r[0], "value") else str(r[0]): r[1]
        for r in alert_status_rows
    }
    for status in AlertStatus:
        alert_statuses.setdefault(status.value, 0)

    # 4. Recent Suspicious Transactions (alerting, one row per transaction)
    suspicious_query = (
        select(Alert, Transaction, RiskAssessment, RiskRule)
        .join(Transaction, Alert.transaction_id == Transaction.id)
        .join(RiskAssessment, Alert.assessment_id == RiskAssessment.id)
        .join(RiskRule, Alert.triggering_rule_id == RiskRule.id)
        .where(version_filter)
        .options(
            joinedload(Transaction.debit_account).joinedload(Account.customer),
            joinedload(Transaction.credit_account).joinedload(Account.customer),
            joinedload(Alert.triggering_rule),
        )
        .order_by(Transaction.occurred_at.desc(), Alert.id.desc())
        .limit(RECENT_ALERT_SCAN_LIMIT)
    )
    suspicious_rows = session.execute(suspicious_query).unique().all()

    recent_suspicious = []
    seen_transaction_ids: set[int] = set()
    for alert, transaction, assessment, rule in suspicious_rows:
        if transaction.id in seen_transaction_ids:
            continue
        seen_transaction_ids.add(transaction.id)

        customer_name = "N/A"
        if transaction.debit_account and transaction.debit_account.customer:
            cust = transaction.debit_account.customer
            customer_name = f"{cust.first_name} {cust.last_name}"
        elif transaction.credit_account and transaction.credit_account.customer:
            cust = transaction.credit_account.customer
            customer_name = f"{cust.first_name} {cust.last_name}"

        recent_suspicious.append(
            {
                "alert_id": alert.id,
                "alert_reference": alert.alert_reference,
                "transaction_id": transaction.id,
                "transaction_reference": transaction.transaction_reference,
                "occurred_at": (
                    transaction.occurred_at.isoformat()
                    if transaction.occurred_at
                    else None
                ),
                "amount": float(transaction.amount),
                "formatted_amount": f"{transaction.amount:,.2f}",
                "currency": (
                    transaction.currency.value
                    if hasattr(transaction.currency, "value")
                    else str(transaction.currency)
                ),
                "transaction_type": (
                    transaction.transaction_type.value
                    if hasattr(transaction.transaction_type, "value")
                    else str(transaction.transaction_type)
                ),
                "customer_name": customer_name,
                "rule_code": rule.code,
                "rule_name": rule.name,
                "score": alert.score,
                "priority": (
                    alert.priority.value
                    if hasattr(alert.priority, "value")
                    else str(alert.priority)
                ),
                "status": (
                    alert.status.value
                    if hasattr(alert.status, "value")
                    else str(alert.status)
                ),
                "summary": alert.summary,
            }
        )
        if len(recent_suspicious) >= RECENT_ALERT_DISPLAY_LIMIT:
            break

    return {
        "model_version": model_version,
        "reference_date": reference_date,
        "alert_threshold": alert_threshold,
        "kpis": kpis,
        "risk_distribution": risk_distribution,
        "risk_distribution_percentages": risk_distribution_percentages,
        "alert_priorities": alert_priorities,
        "alert_statuses": alert_statuses,
        "recent_suspicious_transactions": recent_suspicious,
    }
