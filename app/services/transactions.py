"""Read-only transaction investigation queries and serialization."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models import (
    Account,
    AccountStatusHistory,
    Alert,
    AuditEvent,
    Customer,
    RiskAssessment,
    RiskFinding,
    Transaction,
)

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
DEFAULT_RELATED_LIMIT = 12
MAX_RELATED_LIMIT = 30
MAX_TRANSFER_LEGS = 100


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _iso_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _bounded_int(value: Any, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, 1), maximum)


def find_transaction_id(session: Session, query: str | None) -> int | None:
    """Find a transaction by exact reference or numeric database ID."""

    term = (query or "").strip()[:40]
    if not term:
        return None

    transaction_id = session.scalar(
        select(Transaction.id).where(Transaction.transaction_reference == term)
    )
    if transaction_id is not None:
        return transaction_id

    try:
        numeric_id = int(term)
    except ValueError:
        return None
    return session.scalar(select(Transaction.id).where(Transaction.id == numeric_id))


def _account_options():
    return joinedload(Account.customer)


def _transaction_options():
    return (
        joinedload(Transaction.debit_account).joinedload(Account.customer),
        joinedload(Transaction.credit_account).joinedload(Account.customer),
        joinedload(Transaction.merchant),
        joinedload(Transaction.device),
        joinedload(Transaction.transfer_group),
        selectinload(Transaction.assessments)
        .selectinload(RiskAssessment.findings)
        .joinedload(RiskFinding.rule),
        selectinload(Transaction.alerts),
        selectinload(Transaction.validation_events),
    )


def _serialize_customer(customer: Customer | None) -> dict[str, Any] | None:
    if customer is None:
        return None
    return {
        "id": customer.id,
        "reference": customer.customer_reference,
        "name": f"{customer.first_name} {customer.last_name}".strip(),
        "country_code": customer.country_code,
        "risk_segment": _enum_value(customer.risk_segment),
    }


def _serialize_account(account: Account | None) -> dict[str, Any] | None:
    if account is None:
        return None
    return {
        "id": account.id,
        "number": account.account_number,
        "type": _enum_value(account.account_type),
        "status": _enum_value(account.status),
        "currency": _enum_value(account.currency),
        "customer": _serialize_customer(account.customer),
    }


def _serialize_transaction(transaction: Transaction) -> dict[str, Any]:
    return {
        "id": transaction.id,
        "reference": transaction.transaction_reference,
        "type": _enum_value(transaction.transaction_type),
        "status": _enum_value(transaction.status),
        "amount": f"{transaction.amount:,.2f}",
        "currency": _enum_value(transaction.currency),
        "occurred_at": _iso_datetime(transaction.occurred_at),
        "created_at": _iso_datetime(transaction.created_at),
        "description": transaction.description,
        "debit_account": _serialize_account(transaction.debit_account),
        "credit_account": _serialize_account(transaction.credit_account),
        "transfer_group_id": transaction.transfer_group_id,
    }


def _serialize_finding(finding: RiskFinding) -> dict[str, Any]:
    return {
        "id": finding.id,
        "rule_code": finding.rule_code,
        "rule_name": finding.rule.name if finding.rule else None,
        "score": finding.score,
        "severity": _enum_value(finding.severity),
        "explanation": finding.explanation,
        "evidence": finding.evidence,
        "created_at": _iso_datetime(finding.created_at),
    }


def _serialize_assessment(assessment: RiskAssessment) -> dict[str, Any]:
    findings = sorted(
        assessment.findings,
        key=lambda finding: (-finding.score, finding.id),
    )
    return {
        "id": assessment.id,
        "model_version": assessment.model_version,
        "score": assessment.score,
        "risk_level": _enum_value(assessment.risk_level),
        "status": _enum_value(assessment.status),
        "assessed_at": _iso_datetime(assessment.assessed_at),
        "explanation": assessment.explanation,
        "findings": [_serialize_finding(finding) for finding in findings],
    }


def _serialize_alert(alert: Alert) -> dict[str, Any]:
    return {
        "id": alert.id,
        "reference": alert.alert_reference,
        "status": _enum_value(alert.status),
        "priority": _enum_value(alert.priority),
        "summary": alert.summary,
        "created_at": _iso_datetime(alert.created_at),
    }


def _reference_evidence(finding: RiskFinding) -> set[str]:
    references: set[str] = set()
    if not isinstance(finding.evidence, dict):
        return references
    for key in ("cluster_transaction_references", "cycle_transaction_references"):
        values = finding.evidence.get(key)
        if isinstance(values, list):
            references.update(value for value in values if isinstance(value, str))
    return references


def _related_transactions(
    session: Session,
    transaction: Transaction,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    conditions = []
    account_ids = {
        account_id
        for account_id in (
            transaction.debit_account_id,
            transaction.credit_account_id,
        )
        if account_id is not None
    }
    if transaction.transfer_group_id is not None:
        conditions.append(
            Transaction.transfer_group_id == transaction.transfer_group_id
        )
    if account_ids:
        conditions.append(
            or_(
                Transaction.debit_account_id.in_(account_ids),
                Transaction.credit_account_id.in_(account_ids),
            )
        )
    if transaction.merchant_id is not None:
        conditions.append(Transaction.merchant_id == transaction.merchant_id)
    if transaction.device_id is not None:
        conditions.append(Transaction.device_id == transaction.device_id)

    evidence_references = {
        reference
        for assessment in transaction.assessments
        for finding in assessment.findings
        for reference in _reference_evidence(finding)
    }
    if evidence_references:
        conditions.append(Transaction.transaction_reference.in_(evidence_references))
    if not conditions:
        return []

    candidates = (
        session.scalars(
            select(Transaction)
            .where(
                Transaction.id != transaction.id,
                or_(*conditions),
            )
            .options(
                joinedload(Transaction.debit_account).joinedload(Account.customer),
                joinedload(Transaction.credit_account).joinedload(Account.customer),
            )
            .order_by(Transaction.occurred_at.desc(), Transaction.id.desc())
            .limit(limit)
        )
        .unique()
        .all()
    )

    results = []
    for candidate in candidates:
        reasons = []
        if (
            transaction.transfer_group_id is not None
            and candidate.transfer_group_id == transaction.transfer_group_id
        ):
            reasons.append("Same transfer group")
        if account_ids.intersection(
            {candidate.debit_account_id, candidate.credit_account_id}
        ):
            reasons.append("Shared account")
        if (
            transaction.merchant_id is not None
            and candidate.merchant_id == transaction.merchant_id
        ):
            reasons.append("Same merchant")
        if (
            transaction.device_id is not None
            and candidate.device_id == transaction.device_id
        ):
            reasons.append("Same device")
        if candidate.transaction_reference in evidence_references:
            reasons.append("Referenced by stored risk evidence")
        results.append(
            {
                **_serialize_transaction(candidate),
                "reasons": reasons,
            }
        )
    return results


def _timeline(
    transaction: Transaction,
    transfer_legs: list[Transaction],
    audit_events: list[AuditEvent],
    account_status_history: list[AccountStatusHistory],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    def add(occurred_at: datetime | None, title: str, summary: str, source: str):
        if occurred_at is not None:
            events.append(
                {
                    "occurred_at": occurred_at,
                    "timestamp": _iso_datetime(occurred_at),
                    "title": title,
                    "summary": summary,
                    "source": source,
                }
            )

    add(
        transaction.created_at,
        "Transaction recorded",
        f"Record created for {transaction.transaction_reference}.",
        "Transaction",
    )
    add(
        transaction.occurred_at,
        "Transaction occurred",
        f"{_enum_value(transaction.transaction_type)} · "
        f"{_enum_value(transaction.currency)} {transaction.amount:,.2f}",
        "Transaction",
    )

    account_numbers = {
        account.id: account.account_number
        for account in (transaction.debit_account, transaction.credit_account)
        if account is not None
    }
    for history in account_status_history:
        previous_status = (
            _enum_value(history.previous_status)
            if history.previous_status is not None
            else "not recorded"
        )
        account_number = account_numbers.get(
            history.account_id, str(history.account_id)
        )
        summary = (
            f"Account {account_number}: {previous_status} -> "
            f"{_enum_value(history.new_status)}"
        )
        if history.reason:
            summary += f" · Reason: {history.reason}"
        add(
            history.changed_at,
            "Account status change recorded",
            summary,
            "Account status history",
        )

    for assessment in transaction.assessments:
        add(
            assessment.assessed_at,
            "Risk assessment recorded",
            f"{assessment.model_version} · {_enum_value(assessment.risk_level)} "
            f"risk · score {assessment.score}/100",
            "Risk assessment",
        )
        for finding in assessment.findings:
            add(
                finding.created_at,
                f"Risk finding · {finding.rule_code}",
                finding.explanation,
                "Risk finding",
            )

    for event in transaction.validation_events:
        add(
            event.created_at,
            f"Validation · {event.validation_code}",
            f"{event.message} (current resolution: "
            f"{_enum_value(event.resolution_status)})",
            "Validation event",
        )
        if event.resolved_at is not None:
            add(
                event.resolved_at,
                "Validation resolution recorded",
                f"{event.validation_code} · {_enum_value(event.resolution_status)}",
                "Validation event",
            )

    if transaction.transfer_group is not None:
        group = transaction.transfer_group
        add(
            group.created_at,
            "Transfer group recorded",
            f"{group.transfer_reference} · {_enum_value(group.status)}",
            "Transfer group",
        )
        add(
            group.reconciled_at,
            "Transfer group reconciled",
            f"{group.transfer_reference} · "
            f"{group.currency.value} {group.actual_total:,.2f}",
            "Transfer group",
        )
        for leg in transfer_legs:
            if leg.id != transaction.id:
                add(
                    leg.occurred_at,
                    "Related transfer leg",
                    f"{leg.transaction_reference} · "
                    f"{_enum_value(leg.transaction_type)} · "
                    f"{_enum_value(leg.currency)} {leg.amount:,.2f}",
                    "Transfer",
                )

    for alert in transaction.alerts:
        add(
            alert.created_at,
            "Alert created",
            f"{alert.alert_reference} · {alert.summary}",
            "Alert",
        )
    for event in audit_events:
        add(
            event.occurred_at,
            event.event_type.replace("_", " ").title(),
            event.summary,
            "Alert audit",
        )

    events.sort(
        key=lambda event: (
            event["occurred_at"],
            event["source"],
            event["title"],
        )
    )
    return events


def _transaction_history_rows(
    session: Session,
    account_id: int,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    return [
        _serialize_transaction(transaction)
        for transaction in session.scalars(
            select(Transaction)
            .where(
                or_(
                    Transaction.debit_account_id == account_id,
                    Transaction.credit_account_id == account_id,
                )
            )
            .options(
                joinedload(Transaction.debit_account).joinedload(Account.customer),
                joinedload(Transaction.credit_account).joinedload(Account.customer),
            )
            .order_by(Transaction.occurred_at.desc(), Transaction.id.desc())
            .limit(limit)
        )
        .unique()
        .all()
    ]


def get_transaction_investigation(
    session: Session,
    transaction_id: int,
    *,
    related_limit: int = DEFAULT_RELATED_LIMIT,
) -> dict[str, Any] | None:
    """Return one transaction and its recorded investigative context."""

    transaction = session.scalar(
        select(Transaction)
        .where(Transaction.id == transaction_id)
        .options(*_transaction_options())
    )
    if transaction is None:
        return None

    transfer_legs = [transaction]
    transfer_leg_total = 1
    if transaction.transfer_group_id is not None:
        transfer_leg_total = (
            session.scalar(
                select(func.count(Transaction.id)).where(
                    Transaction.transfer_group_id == transaction.transfer_group_id
                )
            )
            or 0
        )
        other_transfer_legs = (
            session.scalars(
                select(Transaction)
                .where(
                    Transaction.transfer_group_id == transaction.transfer_group_id,
                    Transaction.id != transaction.id,
                )
                .options(
                    joinedload(Transaction.debit_account).joinedload(Account.customer),
                    joinedload(Transaction.credit_account).joinedload(Account.customer),
                )
                .order_by(Transaction.occurred_at, Transaction.id)
                .limit(MAX_TRANSFER_LEGS - 1)
            )
            .unique()
            .all()
        )
        transfer_legs = sorted(
            [transaction, *other_transfer_legs],
            key=lambda leg: (leg.occurred_at, leg.id),
        )

    alert_ids = [alert.id for alert in transaction.alerts]
    audit_events: list[AuditEvent] = []
    if alert_ids:
        audit_events = list(
            session.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.entity_type == "alert",
                    AuditEvent.entity_id.in_(alert_ids),
                )
                .order_by(AuditEvent.occurred_at, AuditEvent.id)
            ).all()
        )

    related_limit = _bounded_int(
        related_limit, DEFAULT_RELATED_LIMIT, MAX_RELATED_LIMIT
    )
    related = _related_transactions(session, transaction, limit=related_limit)
    account_ids = list(
        dict.fromkeys(
            account_id
            for account_id in (
                transaction.debit_account_id,
                transaction.credit_account_id,
            )
            if account_id is not None
        )
    )
    account_status_history = []
    if account_ids:
        account_status_history = list(
            session.scalars(
                select(AccountStatusHistory)
                .where(AccountStatusHistory.account_id.in_(account_ids))
                .order_by(
                    AccountStatusHistory.changed_at,
                    AccountStatusHistory.id,
                )
            ).all()
        )
    account_histories = []
    for account_id in account_ids:
        account = session.scalar(
            select(Account).where(Account.id == account_id).options(_account_options())
        )
        if account is not None:
            account_histories.append(
                {
                    "account": _serialize_account(account),
                    "transactions": _transaction_history_rows(
                        session,
                        account_id,
                        limit=5,
                    ),
                }
            )

    group = transaction.transfer_group
    return {
        "transaction": _serialize_transaction(transaction),
        "merchant": (
            {
                "name": transaction.merchant.name,
                "reference": transaction.merchant.merchant_reference,
                "category": transaction.merchant.category,
                "country_code": transaction.merchant.country_code,
                "risk_level": _enum_value(transaction.merchant.risk_level),
            }
            if transaction.merchant is not None
            else None
        ),
        "device": (
            {
                "type": _enum_value(transaction.device.device_type),
                "first_seen_at": _iso_datetime(transaction.device.first_seen_at),
                "last_seen_at": _iso_datetime(transaction.device.last_seen_at),
                "trusted": transaction.device.is_trusted,
            }
            if transaction.device is not None
            else None
        ),
        "transfer_group": (
            {
                "id": group.id,
                "reference": group.transfer_reference,
                "status": _enum_value(group.status),
                "currency": _enum_value(group.currency),
                "expected_total": f"{group.expected_total:,.2f}",
                "actual_total": f"{group.actual_total:,.2f}",
                "reconciled_at": _iso_datetime(group.reconciled_at),
            }
            if group is not None
            else None
        ),
        "transfer_legs": [_serialize_transaction(leg) for leg in transfer_legs],
        "transfer_legs_pagination": {
            "total": transfer_leg_total,
            "shown": len(transfer_legs),
            "limit": MAX_TRANSFER_LEGS,
            "truncated": transfer_leg_total > len(transfer_legs),
        },
        "assessments": [
            _serialize_assessment(assessment)
            for assessment in sorted(
                transaction.assessments,
                key=lambda item: (item.assessed_at, item.id),
                reverse=True,
            )
        ],
        "alerts": [_serialize_alert(alert) for alert in transaction.alerts],
        "timeline": _timeline(
            transaction,
            transfer_legs,
            audit_events,
            account_status_history,
        ),
        "related_transactions": related,
        "account_histories": account_histories,
    }


def get_account_transaction_history(
    session: Session,
    account_id: int,
    *,
    page: Any = 1,
    per_page: Any = DEFAULT_PAGE_SIZE,
) -> dict[str, Any] | None:
    """Return a bounded, ordered page of debit and credit activity for an account."""

    account = session.scalar(
        select(Account).where(Account.id == account_id).options(_account_options())
    )
    if account is None:
        return None

    current_page = _bounded_int(page, 1, 1_000_000)
    page_size = _bounded_int(per_page, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE)
    filter_condition = or_(
        Transaction.debit_account_id == account_id,
        Transaction.credit_account_id == account_id,
    )
    total = (
        session.scalar(select(func.count(Transaction.id)).where(filter_condition)) or 0
    )
    pages = max(1, (total + page_size - 1) // page_size)
    current_page = min(current_page, pages)
    offset = (current_page - 1) * page_size
    transactions = (
        session.scalars(
            select(Transaction)
            .where(filter_condition)
            .options(
                joinedload(Transaction.debit_account).joinedload(Account.customer),
                joinedload(Transaction.credit_account).joinedload(Account.customer),
            )
            .order_by(Transaction.occurred_at.desc(), Transaction.id.desc())
            .offset(offset)
            .limit(page_size)
        )
        .unique()
        .all()
    )

    items = []
    for transaction in transactions:
        item = _serialize_transaction(transaction)
        item["direction"] = (
            "DEBIT" if transaction.debit_account_id == account_id else "CREDIT"
        )
        counterparty = (
            transaction.credit_account
            if transaction.debit_account_id == account_id
            else transaction.debit_account
        )
        item["counterparty"] = _serialize_account(counterparty)
        items.append(item)

    return {
        "account": _serialize_account(account),
        "items": items,
        "pagination": {
            "page": current_page,
            "per_page": page_size,
            "total": total,
            "pages": pages,
            "has_prev": current_page > 1,
            "has_next": current_page < pages,
            "prev_page": current_page - 1 if current_page > 1 else None,
            "next_page": current_page + 1 if current_page < pages else None,
        },
    }
