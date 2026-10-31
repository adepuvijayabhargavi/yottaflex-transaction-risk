"""Account and account-status validators."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Account, AccountStatusHistory, Customer, User
from app.models.enums import AccountStatus, AccountType, CurrencyCode

from .base import (
    require,
    require_enum,
    require_money,
    require_non_blank,
    require_reference,
    require_timestamp,
    require_timestamp_order,
)

ALLOWED_ACCOUNT_STATUS_TRANSITIONS: dict[AccountStatus, frozenset[AccountStatus]] = {
    AccountStatus.ACTIVE: frozenset(
        {AccountStatus.DORMANT, AccountStatus.FROZEN, AccountStatus.CLOSED}
    ),
    AccountStatus.DORMANT: frozenset(
        {AccountStatus.ACTIVE, AccountStatus.FROZEN, AccountStatus.CLOSED}
    ),
    AccountStatus.FROZEN: frozenset({AccountStatus.ACTIVE, AccountStatus.CLOSED}),
    AccountStatus.CLOSED: frozenset(),
}


def validate_account_status_transition(
    session: Session,
    previous_status: AccountStatus | str | None,
    new_status: AccountStatus | str | None,
    *,
    entity_type: str = "account",
    entity_id: int | None = None,
    record_event: bool = True,
) -> AccountStatus:
    """Validate an allowed account-status transition."""

    new_value = require_enum(
        new_status,
        AccountStatus,
        session=session,
        field="new_status",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    if previous_status is None:
        return new_value

    previous_value = require_enum(
        previous_status,
        AccountStatus,
        session=session,
        field="previous_status",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require(
        new_value != previous_value,
        session=session,
        code="ACCOUNT_STATUS_UNCHANGED",
        message="new_status must differ from previous_status",
        entity_type=entity_type,
        entity_id=entity_id,
        field="new_status",
        details={"status": previous_value.value},
        record_event=record_event,
    )
    require(
        new_value in ALLOWED_ACCOUNT_STATUS_TRANSITIONS[previous_value],
        session=session,
        code="ACCOUNT_STATUS_TRANSITION_INVALID",
        message=(
            f"Account status cannot change from {previous_value.value} "
            f"to {new_value.value}"
        ),
        entity_type=entity_type,
        entity_id=entity_id,
        field="new_status",
        details={
            "previous_status": previous_value.value,
            "new_status": new_value.value,
            "allowed": sorted(
                item.value
                for item in ALLOWED_ACCOUNT_STATUS_TRANSITIONS[previous_value]
            ),
        },
        record_event=record_event,
    )
    return new_value


def validate_account_balance(
    session: Session,
    balance: object,
    overdraft_limit: object,
    *,
    entity_type: str = "account",
    entity_id: int | None = None,
    record_event: bool = True,
) -> None:
    """Validate that a balance stays within its approved overdraft."""

    balance_value = require_money(
        balance,
        session=session,
        field="balance",
        entity_type=entity_type,
        entity_id=entity_id,
        allow_negative=True,
        record_event=record_event,
    )
    overdraft_value = require_money(
        overdraft_limit,
        session=session,
        field="overdraft_limit",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require(
        balance_value >= 0 or overdraft_value > 0,
        session=session,
        code="NEGATIVE_BALANCE_WITHOUT_OVERDRAFT",
        message="A negative balance requires a positive overdraft limit",
        entity_type=entity_type,
        entity_id=entity_id,
        field="balance",
        details={
            "balance": str(balance_value),
            "overdraft_limit": str(overdraft_value),
        },
        record_event=record_event,
    )
    require(
        balance_value >= -overdraft_value,
        session=session,
        code="BALANCE_EXCEEDS_OVERDRAFT",
        message="balance must not be below the negative overdraft limit",
        entity_type=entity_type,
        entity_id=entity_id,
        field="balance",
        details={
            "balance": str(balance_value),
            "overdraft_limit": str(overdraft_value),
        },
        record_event=record_event,
    )


def validate_account(
    session: Session,
    account: Account,
    *,
    record_event: bool = True,
) -> Account:
    """Validate account ownership, status, balance, and close timestamp."""

    entity_type = "account"
    entity_id = account.id
    require_non_blank(
        account.account_number,
        session=session,
        field="account_number",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_reference(
        session,
        Customer,
        account.customer_id,
        field="customer_id",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_enum(
        account.account_type,
        AccountType,
        session=session,
        field="account_type",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_enum(
        account.currency,
        CurrencyCode,
        session=session,
        field="currency",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    status = require_enum(
        account.status,
        AccountStatus,
        session=session,
        field="status",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    validate_account_balance(
        session,
        account.balance,
        account.overdraft_limit,
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_timestamp(
        account.opened_at,
        session=session,
        field="opened_at",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_timestamp_order(
        account.opened_at,
        account.closed_at,
        session=session,
        earlier_field="opened_at",
        later_field="closed_at",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require(
        (status == AccountStatus.CLOSED and account.closed_at is not None)
        or (status != AccountStatus.CLOSED and account.closed_at is None),
        session=session,
        code="CLOSED_TIMESTAMP_MISMATCH",
        message="closed_at must be set only when status is CLOSED",
        entity_type=entity_type,
        entity_id=entity_id,
        field="closed_at",
        details={
            "status": status.value,
            "closed_at": (
                account.closed_at.isoformat() if account.closed_at is not None else None
            ),
        },
        record_event=record_event,
    )
    return account


def validate_account_status_history(
    session: Session,
    history: AccountStatusHistory,
    *,
    record_event: bool = True,
) -> AccountStatusHistory:
    """Validate an append-only account status history entry."""

    entity_type = "account_status_history"
    entity_id = history.id
    account = require_reference(
        session,
        Account,
        history.account_id,
        field="account_id",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    validate_account_status_transition(
        session,
        history.previous_status,
        history.new_status,
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_reference(
        session,
        User,
        history.changed_by_user_id,
        field="changed_by_user_id",
        entity_type=entity_type,
        entity_id=entity_id,
        required=False,
        record_event=record_event,
    )
    require_timestamp(
        history.changed_at,
        session=session,
        field="changed_at",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    if isinstance(history.changed_at, datetime):
        require_timestamp_order(
            account.opened_at,
            history.changed_at,
            session=session,
            earlier_field="account.opened_at",
            later_field="changed_at",
            entity_type=entity_type,
            entity_id=entity_id,
            record_event=record_event,
        )
    return history
