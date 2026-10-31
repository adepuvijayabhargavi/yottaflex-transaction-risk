"""Transfer-group validators."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Account, Customer, Transaction, TransferGroup
from app.models.enums import AccountStatus, CurrencyCode, TransferStatus

from .base import (
    require,
    require_enum,
    require_money,
    require_non_blank,
    require_reference,
    require_timestamp,
    require_timestamp_order,
)


def validate_transfer_group(
    session: Session,
    group: TransferGroup,
    legs: Sequence[Transaction] | None = None,
    *,
    record_event: bool = True,
) -> TransferGroup:
    """Validate transfer totals, currencies, accounts, and reconciliation."""

    entity_type = "transfer_group"
    entity_id = group.id
    require_non_blank(
        group.transfer_reference,
        session=session,
        field="transfer_reference",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    status = require_enum(
        group.status,
        TransferStatus,
        session=session,
        field="status",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    currency = require_enum(
        group.currency,
        CurrencyCode,
        session=session,
        field="currency",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    expected_total = require_money(
        group.expected_total,
        session=session,
        field="expected_total",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    actual_total = require_money(
        group.actual_total,
        session=session,
        field="actual_total",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_reference(
        session,
        Customer,
        group.initiated_by_customer_id,
        field="initiated_by_customer_id",
        entity_type=entity_type,
        entity_id=entity_id,
        required=False,
        record_event=record_event,
    )
    if group.reconciled_at is not None:
        require_timestamp(
            group.reconciled_at,
            session=session,
            field="reconciled_at",
            entity_type=entity_type,
            entity_id=entity_id,
            code="INVALID_TIMESTAMP",
            record_event=record_event,
        )
    require_timestamp_order(
        group.created_at,
        group.reconciled_at,
        session=session,
        earlier_field="created_at",
        later_field="reconciled_at",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )

    leg_list = list(legs) if legs is not None else list(group.transactions)
    source_total = Decimal(0)
    destination_total = Decimal(0)
    for leg in leg_list:
        require_non_blank(
            leg.transaction_reference,
            session=session,
            field="transaction_reference",
            entity_type=entity_type,
            entity_id=entity_id,
            record_event=record_event,
        )
        leg_amount = require_money(
            leg.amount,
            session=session,
            field="amount",
            entity_type=entity_type,
            entity_id=entity_id,
            positive=True,
            record_event=record_event,
        )
        leg_currency = require_enum(
            leg.currency,
            CurrencyCode,
            session=session,
            field="currency",
            entity_type=entity_type,
            entity_id=entity_id,
            record_event=record_event,
        )
        require(
            leg_currency == currency,
            session=session,
            code="TRANSFER_CURRENCY_MISMATCH",
            message="All transfer legs must use the group currency",
            entity_type=entity_type,
            entity_id=entity_id,
            field="currency",
            details={
                "transaction_currency": leg_currency.value,
                "group_currency": currency.value,
            },
            record_event=record_event,
        )
        if group.id is not None and leg.transfer_group_id is not None:
            require(
                leg.transfer_group_id == group.id,
                session=session,
                code="TRANSFER_LEG_GROUP_MISMATCH",
                message="Transfer leg belongs to a different group",
                entity_type=entity_type,
                entity_id=entity_id,
                field="transfer_group_id",
                details={
                    "transaction_group_id": leg.transfer_group_id,
                    "group_id": group.id,
                },
                record_event=record_event,
            )

        debit_account = require_reference(
            session,
            Account,
            leg.debit_account_id,
            field="debit_account_id",
            entity_type=entity_type,
            entity_id=entity_id,
            required=False,
            record_event=record_event,
        )
        credit_account = require_reference(
            session,
            Account,
            leg.credit_account_id,
            field="credit_account_id",
            entity_type=entity_type,
            entity_id=entity_id,
            required=False,
            record_event=record_event,
        )
        require(
            debit_account is not None or credit_account is not None,
            session=session,
            code="TRANSFER_LEG_WITHOUT_ACCOUNT",
            message="Each transfer leg requires a source or destination account",
            entity_type=entity_type,
            entity_id=entity_id,
            field="transaction_reference",
            details={"transaction_reference": leg.transaction_reference},
            record_event=record_event,
        )
        if debit_account is not None:
            source_total += leg_amount
            _validate_transfer_account(
                session,
                group,
                debit_account,
                side="source",
                currency=currency,
                record_event=record_event,
            )
        if credit_account is not None:
            destination_total += leg_amount
            _validate_transfer_account(
                session,
                group,
                credit_account,
                side="destination",
                currency=currency,
                record_event=record_event,
            )

    if status == TransferStatus.RECONCILED:
        require(
            group.reconciled_at is not None,
            session=session,
            code="TRANSFER_RECONCILED_WITHOUT_TIMESTAMP",
            message="RECONCILED transfer groups require reconciled_at",
            entity_type=entity_type,
            entity_id=entity_id,
            field="reconciled_at",
            record_event=record_event,
        )
        require(
            bool(leg_list),
            session=session,
            code="TRANSFER_WITHOUT_LEGS",
            message="RECONCILED transfer groups require at least one leg",
            entity_type=entity_type,
            entity_id=entity_id,
            field="transactions",
            record_event=record_event,
        )
        require(
            actual_total == expected_total,
            session=session,
            code="TRANSFER_TOTALS_MISMATCH",
            message="actual_total must equal expected_total when reconciled",
            entity_type=entity_type,
            entity_id=entity_id,
            field="actual_total",
            details={
                "expected_total": str(expected_total),
                "actual_total": str(actual_total),
            },
            record_event=record_event,
        )
        require(
            source_total == expected_total,
            session=session,
            code="TRANSFER_SOURCE_TOTAL_MISMATCH",
            message="Source leg amounts must equal expected_total when reconciled",
            entity_type=entity_type,
            entity_id=entity_id,
            field="transactions",
            details={
                "expected_total": str(expected_total),
                "source_total": str(source_total),
            },
            record_event=record_event,
        )
        require(
            destination_total == expected_total,
            session=session,
            code="TRANSFER_DESTINATION_TOTAL_MISMATCH",
            message=(
                "Destination leg amounts must equal expected_total when reconciled"
            ),
            entity_type=entity_type,
            entity_id=entity_id,
            field="transactions",
            details={
                "expected_total": str(expected_total),
                "destination_total": str(destination_total),
            },
            record_event=record_event,
        )
    return group


def _validate_transfer_account(
    session: Session,
    group: TransferGroup,
    account: Account,
    *,
    side: str,
    currency: CurrencyCode,
    record_event: bool,
) -> None:
    entity_type = "transfer_group"
    entity_id = group.id
    require(
        account.status != AccountStatus.CLOSED,
        session=session,
        code="TRANSFER_CLOSED_ACCOUNT",
        message=f"Transfer {side} account is closed",
        entity_type=entity_type,
        entity_id=entity_id,
        field=f"{side}_account_id",
        details={
            "account_id": account.id,
            "account_status": getattr(account.status, "value", account.status),
        },
        record_event=record_event,
    )
    require(
        account.currency == currency,
        session=session,
        code="TRANSFER_ACCOUNT_CURRENCY_MISMATCH",
        message=f"Transfer {side} account currency must match group currency",
        entity_type=entity_type,
        entity_id=entity_id,
        field=f"{side}_account_id",
        details={
            "account_currency": getattr(
                account.currency,
                "value",
                account.currency,
            ),
            "group_currency": getattr(currency, "value", currency),
        },
        record_event=record_event,
    )
