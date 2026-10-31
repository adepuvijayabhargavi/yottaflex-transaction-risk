"""Transaction validators."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import (
    Account,
    Device,
    Merchant,
    Transaction,
    TransferGroup,
)
from app.models.enums import (
    AccountStatus,
    CurrencyCode,
    TransactionStatus,
    TransactionType,
)

from .base import (
    require,
    require_enum,
    require_money,
    require_non_blank,
    require_reference,
    require_timestamp,
    require_timestamp_order,
)


def validate_transaction(
    session: Session,
    transaction: Transaction,
    *,
    now: datetime | None = None,
    record_event: bool = True,
) -> Transaction:
    """Validate transaction references, type, accounts, and timestamps."""

    entity_type = "transaction"
    entity_id = transaction.id
    transaction_id = transaction.id
    require_non_blank(
        transaction.transaction_reference,
        session=session,
        field="transaction_reference",
        entity_type=entity_type,
        entity_id=entity_id,
        transaction_id=transaction_id,
        record_event=record_event,
    )
    transaction_type = require_enum(
        transaction.transaction_type,
        TransactionType,
        session=session,
        field="transaction_type",
        entity_type=entity_type,
        entity_id=entity_id,
        transaction_id=transaction_id,
        record_event=record_event,
    )
    require_enum(
        transaction.status,
        TransactionStatus,
        session=session,
        field="status",
        entity_type=entity_type,
        entity_id=entity_id,
        transaction_id=transaction_id,
        record_event=record_event,
    )
    currency = require_enum(
        transaction.currency,
        CurrencyCode,
        session=session,
        field="currency",
        entity_type=entity_type,
        entity_id=entity_id,
        transaction_id=transaction_id,
        record_event=record_event,
    )
    require_money(
        transaction.amount,
        session=session,
        field="amount",
        entity_type=entity_type,
        entity_id=entity_id,
        positive=True,
        transaction_id=transaction_id,
        record_event=record_event,
    )
    occurred_at = require_timestamp(
        transaction.occurred_at,
        session=session,
        field="occurred_at",
        entity_type=entity_type,
        entity_id=entity_id,
        transaction_id=transaction_id,
        record_event=record_event,
    )

    debit_account = require_reference(
        session,
        Account,
        transaction.debit_account_id,
        field="debit_account_id",
        entity_type=entity_type,
        entity_id=entity_id,
        required=transaction_type
        in {TransactionType.OUTGOING, TransactionType.INTERNAL},
        transaction_id=transaction_id,
        record_event=record_event,
    )
    credit_account = require_reference(
        session,
        Account,
        transaction.credit_account_id,
        field="credit_account_id",
        entity_type=entity_type,
        entity_id=entity_id,
        required=transaction_type
        in {TransactionType.INCOMING, TransactionType.INTERNAL},
        transaction_id=transaction_id,
        record_event=record_event,
    )
    require_reference(
        session,
        Merchant,
        transaction.merchant_id,
        field="merchant_id",
        entity_type=entity_type,
        entity_id=entity_id,
        required=False,
        transaction_id=transaction_id,
        record_event=record_event,
    )
    require_reference(
        session,
        Device,
        transaction.device_id,
        field="device_id",
        entity_type=entity_type,
        entity_id=entity_id,
        required=False,
        transaction_id=transaction_id,
        record_event=record_event,
    )
    transfer_group = require_reference(
        session,
        TransferGroup,
        transaction.transfer_group_id,
        field="transfer_group_id",
        entity_type=entity_type,
        entity_id=entity_id,
        required=False,
        transaction_id=transaction_id,
        record_event=record_event,
    )

    if transaction_type == TransactionType.OUTGOING:
        require(
            debit_account is not None and credit_account is None,
            session=session,
            code="TRANSACTION_ACCOUNT_TYPE_MISMATCH",
            message="OUTGOING transactions require only a debit account",
            entity_type=entity_type,
            entity_id=entity_id,
            field="transaction_type",
            transaction_id=transaction_id,
            record_event=record_event,
        )
    elif transaction_type == TransactionType.INCOMING:
        require(
            credit_account is not None and debit_account is None,
            session=session,
            code="TRANSACTION_ACCOUNT_TYPE_MISMATCH",
            message="INCOMING transactions require only a credit account",
            entity_type=entity_type,
            entity_id=entity_id,
            field="transaction_type",
            transaction_id=transaction_id,
            record_event=record_event,
        )
    else:
        require(
            debit_account is not None
            and credit_account is not None
            and debit_account.id != credit_account.id,
            session=session,
            code="TRANSACTION_ACCOUNT_TYPE_MISMATCH",
            message="INTERNAL transactions require two different accounts",
            entity_type=entity_type,
            entity_id=entity_id,
            field="transaction_type",
            transaction_id=transaction_id,
            record_event=record_event,
        )

    if transfer_group is not None:
        require(
            transfer_group.currency == currency,
            session=session,
            code="TRANSACTION_CURRENCY_MISMATCH",
            message="transaction currency must match its transfer group",
            entity_type=entity_type,
            entity_id=entity_id,
            field="currency",
            details={
                "transaction_currency": currency.value,
                "transfer_currency": transfer_group.currency.value,
            },
            transaction_id=transaction_id,
            record_event=record_event,
        )

    _validate_transaction_account(
        session,
        transaction,
        debit_account,
        snapshot=transaction.debit_account_status_snapshot,
        side="debit",
        currency=currency,
        occurred_at=occurred_at,
        record_event=record_event,
    )
    _validate_transaction_account(
        session,
        transaction,
        credit_account,
        snapshot=transaction.credit_account_status_snapshot,
        side="credit",
        currency=currency,
        occurred_at=occurred_at,
        record_event=record_event,
    )

    if now is not None:
        require(
            occurred_at <= now,
            session=session,
            code="TRANSACTION_IN_FUTURE",
            message="occurred_at must not be in the future",
            entity_type=entity_type,
            entity_id=entity_id,
            field="occurred_at",
            details={"occurred_at": occurred_at.isoformat(), "now": now.isoformat()},
            transaction_id=transaction_id,
            record_event=record_event,
        )
    return transaction


def _validate_transaction_account(
    session: Session,
    transaction: Transaction,
    account: Account | None,
    *,
    snapshot: AccountStatus | None,
    side: str,
    currency: CurrencyCode,
    occurred_at: datetime,
    record_event: bool,
) -> None:
    entity_type = "transaction"
    entity_id = transaction.id
    transaction_id = transaction.id
    snapshot_field = f"{side}_account_status_snapshot"

    if account is None:
        require(
            snapshot is None,
            session=session,
            code="ACCOUNT_SNAPSHOT_WITHOUT_ACCOUNT",
            message=f"{snapshot_field} requires a {side} account",
            entity_type=entity_type,
            entity_id=entity_id,
            field=snapshot_field,
            transaction_id=transaction_id,
            record_event=record_event,
        )
        return

    require(
        account.status != AccountStatus.CLOSED and snapshot != AccountStatus.CLOSED,
        session=session,
        code="TRANSACTION_CLOSED_ACCOUNT",
        message=f"Transaction references a closed {side} account",
        entity_type=entity_type,
        entity_id=entity_id,
        field=f"{side}_account_id",
        details={
            "account_id": account.id,
            "account_status": getattr(account.status, "value", account.status),
            "snapshot": getattr(snapshot, "value", snapshot),
        },
        transaction_id=transaction_id,
        record_event=record_event,
    )
    require(
        snapshot is not None,
        session=session,
        code="ACCOUNT_SNAPSHOT_INVALID",
        message=f"{snapshot_field} is required for a {side} account",
        entity_type=entity_type,
        entity_id=entity_id,
        field=snapshot_field,
        transaction_id=transaction_id,
        record_event=record_event,
    )
    require(
        account.currency == currency,
        session=session,
        code="TRANSACTION_CURRENCY_MISMATCH",
        message=f"{side} account currency must match transaction currency",
        entity_type=entity_type,
        entity_id=entity_id,
        field=f"{side}_account_id",
        details={
            "account_currency": getattr(
                account.currency,
                "value",
                account.currency,
            ),
            "transaction_currency": getattr(currency, "value", currency),
        },
        transaction_id=transaction_id,
        record_event=record_event,
    )
    require_timestamp_order(
        account.opened_at,
        occurred_at,
        session=session,
        earlier_field=f"{side}_account.opened_at",
        later_field="occurred_at",
        entity_type=entity_type,
        entity_id=entity_id,
        code="TRANSACTION_BEFORE_ACCOUNT_OPEN",
        transaction_id=transaction_id,
        record_event=record_event,
    )
