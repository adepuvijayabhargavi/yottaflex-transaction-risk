"""Deterministic synthetic transaction dataset generation."""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import count
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.evaluation import GroundTruth
from app.models import (
    Account,
    AccountStatusHistory,
    Customer,
    DatasetRun,
    Device,
    Merchant,
    RiskRule,
    Transaction,
    TransferGroup,
)
from app.models.base import utc_now
from app.models.enums import (
    AccountStatus,
    AccountType,
    CurrencyCode,
    CustomerRiskSegment,
    DatasetRunStatus,
    DeviceType,
    MerchantRiskLevel,
    RiskSeverity,
    TransactionStatus,
    TransactionType,
    TransferStatus,
)
from app.services.reproducibility.checksums import compute_run_checksums

from .profiles import DatasetProfile

GENERATOR_VERSION = "1.0.0"
OPENING_BALANCE = Decimal("1000000.00")
DEFAULT_CURRENCY = CurrencyCode.USD

PATTERN_COUNTS = {
    "HIGH_TRANSACTION_VELOCITY": 4,
    "NEW_DEVICE_ACTIVITY": 3,
    "CIRCULAR_FUND_TRANSFER": 3,
    "DORMANT_ACCOUNT_REACTIVATION": 3,
    "HIGH_VALUE_TRANSACTION": 4,
    "REPEATED_TRANSACTIONS": 3,
}
_BASE_POSITIVE_LABEL_COUNT = sum(PATTERN_COUNTS.values())


def pattern_counts_for_target(positive_label_target: int) -> dict[str, int]:
    """Scale the pilot pattern proportions to a supported positive-label target."""

    if (
        positive_label_target < _BASE_POSITIVE_LABEL_COUNT
        or positive_label_target % _BASE_POSITIVE_LABEL_COUNT != 0
    ):
        raise ValueError(
            "Positive-label target must be a positive multiple of "
            f"{_BASE_POSITIVE_LABEL_COUNT}."
        )

    scale = positive_label_target // _BASE_POSITIVE_LABEL_COUNT
    return {pattern: count * scale for pattern, count in PATTERN_COUNTS.items()}


FIRST_NAMES = (
    "Aarav",
    "Amelia",
    "Ananya",
    "Arjun",
    "Ava",
    "Daniel",
    "Elena",
    "Ethan",
    "Fatima",
    "Grace",
    "Hassan",
    "Isabella",
    "Kabir",
    "Liam",
    "Maya",
    "Noah",
    "Priya",
    "Rohan",
    "Sofia",
    "Vikram",
)
LAST_NAMES = (
    "Ahmed",
    "Bennett",
    "Chandra",
    "Davis",
    "Fernandes",
    "Garcia",
    "Gupta",
    "Hughes",
    "Iyer",
    "Johnson",
    "Khan",
    "Kumar",
    "Miller",
    "Nair",
    "Patel",
    "Rao",
    "Sharma",
    "Singh",
    "Taylor",
    "Wilson",
)
COUNTRY_CODES = ("US", "GB", "DE", "IN", "AE", "SG")
MERCHANT_CATEGORIES = (
    "RETAIL",
    "GROCERY",
    "TRAVEL",
    "ELECTRONICS",
    "GAMBLING",
    "CRYPTO",
    "UTILITIES",
    "ENTERTAINMENT",
)
DEVICE_TYPES = (
    DeviceType.MOBILE,
    DeviceType.TABLET,
    DeviceType.DESKTOP,
    DeviceType.UNKNOWN,
)
ACCOUNT_TYPES = (
    AccountType.CHECKING,
    AccountType.SAVINGS,
    AccountType.BUSINESS,
    AccountType.WALLET,
)


@dataclass(frozen=True, slots=True)
class RuleSpec:
    code: str
    name: str
    category: str
    severity: RiskSeverity
    score_weight: int
    configuration: dict[str, Any]


RISK_RULES: tuple[RuleSpec, ...] = (
    RuleSpec(
        "HIGH_TRANSACTION_VELOCITY",
        "High transaction velocity",
        "velocity",
        RiskSeverity.HIGH,
        20,
        {"transaction_count": 4, "window_minutes": 60},
    ),
    RuleSpec(
        "NEW_DEVICE_ACTIVITY",
        "New device activity",
        "device",
        RiskSeverity.HIGH,
        18,
        {"device_age_hours": 24, "require_untrusted": True},
    ),
    RuleSpec(
        "CIRCULAR_FUND_TRANSFER",
        "Circular fund transfer",
        "network",
        RiskSeverity.CRITICAL,
        30,
        {"max_cycle_length": 4, "window_hours": 24},
    ),
    RuleSpec(
        "DORMANT_ACCOUNT_REACTIVATION",
        "Dormant account reactivation",
        "dormancy",
        RiskSeverity.HIGH,
        22,
        {"dormant_days": 90},
    ),
    RuleSpec(
        "HIGH_VALUE_TRANSACTION",
        "High value transaction",
        "amount",
        RiskSeverity.HIGH,
        20,
        {"amount_threshold": 50000, "currency": "USD"},
    ),
    RuleSpec(
        "REPEATED_TRANSACTIONS",
        "Repeated transactions",
        "repeat",
        RiskSeverity.MEDIUM,
        15,
        {"repeat_count": 3, "window_minutes": 30},
    ),
    RuleSpec(
        "RAPID_PASS_THROUGH",
        "Rapid pass-through",
        "layering",
        RiskSeverity.HIGH,
        18,
        {"max_holding_minutes": 15},
    ),
    RuleSpec(
        "UNUSUAL_MERCHANT_CATEGORY",
        "Unusual merchant category",
        "merchant",
        RiskSeverity.MEDIUM,
        12,
        {"categories": ["GAMBLING", "CRYPTO"]},
    ),
    RuleSpec(
        "CROSS_BORDER_ACTIVITY",
        "Cross-border activity",
        "geography",
        RiskSeverity.MEDIUM,
        10,
        {"country_codes": ["AE", "GB"]},
    ),
    RuleSpec(
        "MULTIPLE_ACCOUNTS_SAME_DEVICE",
        "Multiple accounts on one device",
        "identity",
        RiskSeverity.MEDIUM,
        12,
        {"account_threshold": 3},
    ),
    RuleSpec(
        "NIGHTTIME_TRANSACTION",
        "Nighttime transaction",
        "time",
        RiskSeverity.LOW,
        8,
        {"start_hour": 0, "end_hour": 5},
    ),
    RuleSpec(
        "LARGE_CASH_WITHDRAWAL",
        "Large cash withdrawal",
        "cash",
        RiskSeverity.MEDIUM,
        10,
        {"amount_threshold": 10000},
    ),
)


@dataclass(slots=True)
class GenerationResult:
    """Summary of a completed deterministic generation run."""

    run: DatasetRun
    counts: dict[str, Any]
    checksums: dict[str, Any]
    pattern_counts: dict[str, int]


def _rng(profile: DatasetProfile, stream: str) -> random.Random:
    return random.Random(f"{profile.seed}:{stream}")


def _money(cents: int) -> Decimal:
    return (Decimal(cents) / Decimal(100)).quantize(Decimal("0.01"))


def _at(
    reference: datetime,
    *,
    days: int = 0,
    hours: int = 0,
    minutes: int = 0,
    seconds: int = 0,
) -> datetime:
    return reference - timedelta(
        days=days,
        hours=hours,
        minutes=minutes,
        seconds=seconds,
    )


def _reference(prefix: str, kind: str, number: int, width: int) -> str:
    return f"{prefix}{kind}-{number:0{width}d}"


def _status_counts(account_target: int) -> tuple[int, int, int, int]:
    dormant = max(12, account_target * 8 // 100)
    frozen = max(5, account_target * 3 // 100)
    closed = max(5, account_target * 3 // 100)
    active = account_target - dormant - frozen - closed
    if active < 12:
        raise ValueError("Pilot profile requires at least twelve active accounts.")
    return active, dormant, frozen, closed


def _accounts_per_customer(customer_target: int, account_target: int) -> list[int]:
    base, extra = divmod(account_target, customer_target)
    return [base + (1 if index < extra else 0) for index in range(customer_target)]


def _devices_per_customer(customer_target: int, device_target: int) -> list[int]:
    base, extra = divmod(device_target, customer_target)
    return [base + (1 if index < extra else 0) for index in range(customer_target)]


def _upsert_risk_rules(
    session: Session,
    profile: DatasetProfile,
) -> list[RiskRule]:
    effective_from = _at(profile.reference_datetime, days=365)
    codes = [spec.code for spec in RISK_RULES]
    existing = {
        rule.code: rule
        for rule in session.scalars(
            select(RiskRule).where(
                RiskRule.code.in_(codes),
                RiskRule.version == 1,
            )
        ).all()
    }

    rules: list[RiskRule] = []
    for spec in RISK_RULES:
        rule = existing.get(spec.code)
        if rule is None:
            rule = RiskRule(
                code=spec.code,
                version=1,
                name=spec.name,
                description=spec.name,
                category=spec.category,
                severity=spec.severity,
                score_weight=spec.score_weight,
                configuration=spec.configuration,
                is_active=True,
                effective_from=effective_from,
                created_at=effective_from,
                updated_at=effective_from,
            )
            session.add(rule)
        else:
            rule.name = spec.name
            rule.description = spec.name
            rule.category = spec.category
            rule.severity = spec.severity
            rule.score_weight = spec.score_weight
            rule.configuration = spec.configuration
            rule.is_active = True
            rule.effective_from = effective_from
            rule.effective_to = None
            rule.updated_at = effective_from
        rules.append(rule)
    session.flush()
    return rules


def _build_customers(
    profile: DatasetProfile,
    prefix: str,
) -> list[Customer]:
    rng = _rng(profile, "customers")
    target = profile.target("customers")
    customers: list[Customer] = []

    for index in range(1, target + 1):
        first_name = rng.choice(FIRST_NAMES)
        last_name = rng.choice(LAST_NAMES)
        onboarding = profile.reference_datetime.date() - timedelta(
            days=rng.randint(365, 3650),
        )
        created_at = datetime.combine(onboarding, datetime.min.time())
        customer = Customer(
            customer_reference=_reference(
                prefix,
                "CUST",
                index,
                4,
            ),
            first_name=first_name,
            last_name=last_name,
            email=f"{first_name.lower()}.{last_name.lower()}.{index:04d}@example.test",
            phone=f"+1-555-{index:07d}",
            country_code=rng.choice(COUNTRY_CODES),
            risk_segment=rng.choices(
                [
                    CustomerRiskSegment.LOW,
                    CustomerRiskSegment.STANDARD,
                    CustomerRiskSegment.HIGH,
                ],
                weights=[2, 7, 1],
            )[0],
            onboarding_date=onboarding,
            is_active=True,
            created_at=created_at,
            updated_at=created_at,
        )
        customers.append(customer)

    return customers


def _build_accounts(
    profile: DatasetProfile,
    customers: Sequence[Customer],
    prefix: str,
) -> tuple[
    list[Account],
    list[AccountStatusHistory],
    int,
    list[Account],
]:
    rng = _rng(profile, "accounts")
    account_target = profile.target("accounts")
    active_count, dormant_count, frozen_count, _closed_count = _status_counts(
        account_target
    )
    counts = _accounts_per_customer(len(customers), account_target)
    if sum(counts) != account_target:
        raise ValueError("Account distribution does not match the profile target.")

    accounts: list[Account] = []
    history: list[AccountStatusHistory] = []
    number = 0

    for customer, account_count in zip(customers, counts, strict=True):
        for _ in range(account_count):
            number += 1
            if number <= active_count:
                status = AccountStatus.ACTIVE
            elif number <= active_count + dormant_count:
                status = AccountStatus.DORMANT
            elif number <= active_count + dormant_count + frozen_count:
                status = AccountStatus.FROZEN
            else:
                status = AccountStatus.CLOSED

            opened_at = _at(
                profile.reference_datetime,
                days=rng.randint(400, 2000),
                minutes=rng.randint(0, 1440),
            )
            changed_at: datetime | None = None
            reason: str | None = None
            closed_at: datetime | None = None

            if status is AccountStatus.DORMANT:
                changed_at = max(
                    opened_at + timedelta(days=1),
                    _at(profile.reference_datetime, days=rng.randint(180, 500)),
                )
                reason = "PERIODIC_DORMANCY_REVIEW"
            elif status is AccountStatus.FROZEN:
                changed_at = max(
                    opened_at + timedelta(days=1),
                    _at(profile.reference_datetime, days=rng.randint(10, 90)),
                )
                reason = "RISK_REVIEW_FREEZE"
            elif status is AccountStatus.CLOSED:
                closed_at = max(
                    opened_at + timedelta(days=1),
                    _at(profile.reference_datetime, days=rng.randint(10, 200)),
                )
                changed_at = closed_at
                reason = "CUSTOMER_REQUEST_CLOSE"

            account = Account(
                account_number=_reference(
                    prefix,
                    "ACC",
                    number,
                    4,
                ),
                customer_id=customer.id,
                account_type=rng.choice(ACCOUNT_TYPES),
                currency=DEFAULT_CURRENCY,
                status=status,
                balance=OPENING_BALANCE,
                overdraft_limit=Decimal("0.00"),
                opened_at=opened_at,
                closed_at=closed_at,
                created_at=opened_at,
                updated_at=opened_at,
            )
            accounts.append(account)

            if changed_at is not None:
                history.append(
                    AccountStatusHistory(
                        account=account,
                        previous_status=AccountStatus.ACTIVE,
                        new_status=status,
                        reason=reason,
                        changed_at=changed_at,
                    )
                )

    return (
        accounts,
        history,
        active_count,
        accounts[active_count : active_count + dormant_count],
    )


def _build_devices(
    profile: DatasetProfile,
    customers: Sequence[Customer],
    prefix: str,
) -> list[Device]:
    rng = _rng(profile, "devices")
    counts = _devices_per_customer(len(customers), profile.target("devices"))
    devices: list[Device] = []
    number = 0

    for customer, device_count in zip(customers, counts, strict=True):
        for _ in range(device_count):
            number += 1
            first_seen = _at(
                profile.reference_datetime,
                days=rng.randint(30, 500),
                minutes=rng.randint(0, 1440),
            )
            last_seen = _at(
                profile.reference_datetime,
                days=rng.randint(0, 20),
                minutes=rng.randint(0, 1440),
            )
            last_seen = max(last_seen, first_seen + timedelta(days=1))
            devices.append(
                Device(
                    device_fingerprint=_reference(
                        prefix,
                        "DEV",
                        number,
                        6,
                    ),
                    customer_id=customer.id,
                    device_type=rng.choice(DEVICE_TYPES),
                    first_seen_at=first_seen,
                    last_seen_at=last_seen,
                    is_trusted=rng.random() < 0.8,
                    created_at=first_seen,
                    updated_at=first_seen,
                )
            )

    return devices


def _build_merchants(profile: DatasetProfile, prefix: str) -> list[Merchant]:
    rng = _rng(profile, "merchants")
    merchants: list[Merchant] = []
    created_at = _at(profile.reference_datetime, days=1000)

    for index in range(1, profile.target("merchants") + 1):
        category = rng.choice(MERCHANT_CATEGORIES)
        merchants.append(
            Merchant(
                merchant_reference=_reference(
                    prefix,
                    "MER",
                    index,
                    4,
                ),
                name=f"{category.title()} Merchant {index:03d}",
                category=category,
                country_code=rng.choice(COUNTRY_CODES),
                risk_level=rng.choices(
                    [
                        MerchantRiskLevel.LOW,
                        MerchantRiskLevel.STANDARD,
                        MerchantRiskLevel.HIGH,
                    ],
                    weights=[5, 4, 1],
                )[0],
                is_active=rng.random() > 0.06,
                created_at=created_at,
                updated_at=created_at,
            )
        )

    return merchants


def _trusted_device(
    devices_by_customer: dict[int, list[Device]],
    customer_id: int,
    rng: random.Random,
) -> Device | None:
    devices = devices_by_customer.get(customer_id, [])
    if not devices:
        return None
    trusted = [device for device in devices if device.is_trusted]
    return rng.choice(trusted or devices)


def _build_transfer_groups(
    profile: DatasetProfile,
    session: Session,
    accounts: Sequence[Account],
    active_count: int,
    devices_by_customer: dict[int, list[Device]],
    tx_numbers: count,
    prefix: str,
    pattern_counts: dict[str, int],
) -> tuple[list[TransferGroup], list[Transaction], dict[str, str]]:
    rng = _rng(profile, "transfer_groups")
    target = profile.target("transfer_groups")
    if target < 1:
        return [], [], {}

    circular_label_count = pattern_counts["CIRCULAR_FUND_TRANSFER"]
    circular_group_count, remainder = divmod(circular_label_count, 3)
    if remainder:
        raise ValueError("Circular-transfer labels must form complete 3-leg groups.")
    if circular_group_count > target:
        raise ValueError("Transfer-group target is too small for circular labels.")

    pending_count = max(1, target // 25)
    failed_count = max(1, target // 50)
    reconciled_count = target - pending_count - failed_count
    if reconciled_count < 1:
        raise ValueError("Transfer-group target is too small.")

    group_pool = list(accounts[: active_count - 9])
    if len(group_pool) < 4:
        raise ValueError("Not enough active accounts to create transfer groups.")

    groups: list[TransferGroup] = []
    group_legs: list[
        tuple[
            TransferGroup,
            Sequence[Account],
            list[Decimal],
            list[TransactionStatus],
            datetime,
            bool,
        ]
    ] = []

    for group_index in range(1, target + 1):
        circular = group_index <= circular_group_count
        chosen = rng.sample(group_pool, 3) if circular else rng.sample(group_pool, 4)
        start = _at(
            profile.reference_datetime,
            days=rng.randint(1, 90),
            hours=rng.randint(0, 23),
            minutes=rng.randint(0, 59),
        )

        base_cents = rng.randint(1000, 500000)
        amounts = [_money(base_cents + rng.randint(0, 50000)) for _ in range(3)]

        if group_index <= reconciled_count:
            status = TransferStatus.RECONCILED
            leg_statuses = [TransactionStatus.POSTED] * 3
            reconciled_at = start + timedelta(hours=4, minutes=10)
        elif group_index <= reconciled_count + pending_count:
            status = TransferStatus.PENDING
            leg_statuses = [
                TransactionStatus.POSTED,
                TransactionStatus.POSTED,
                TransactionStatus.PENDING,
            ]
            reconciled_at = None
        else:
            status = TransferStatus.FAILED
            leg_statuses = [
                TransactionStatus.FAILED,
                TransactionStatus.POSTED,
                TransactionStatus.POSTED,
            ]
            reconciled_at = None

        expected_total = sum(amounts, Decimal("0.00"))
        actual_total = sum(
            (
                amount
                for amount, leg_status in zip(amounts, leg_statuses, strict=True)
                if leg_status == TransactionStatus.POSTED
            ),
            Decimal("0.00"),
        )

        group = TransferGroup(
            transfer_reference=_reference(prefix, "TRF", group_index, 4),
            initiated_by_customer_id=chosen[0].customer_id,
            status=status,
            expected_total=expected_total,
            actual_total=actual_total,
            currency=DEFAULT_CURRENCY,
            reconciled_at=reconciled_at,
            created_at=start - timedelta(minutes=5),
            updated_at=start - timedelta(minutes=5),
        )
        groups.append(group)
        group_legs.append((group, chosen, amounts, leg_statuses, start, circular))

    session.add_all(groups)
    session.flush()

    transactions: list[Transaction] = []
    labels: dict[str, str] = {}
    for group, chosen, amounts, leg_statuses, start, circular in group_legs:
        pairs = ((0, 1), (1, 2), (2, 0)) if circular else ((0, 1), (0, 2), (0, 3))
        for leg_index, (source_index, destination_index) in enumerate(pairs):
            source = chosen[source_index]
            destination = chosen[destination_index]
            occurred_at = start + timedelta(hours=2 * leg_index)
            transaction_reference = _reference(
                prefix,
                "TXN",
                next(tx_numbers),
                6,
            )
            device = _trusted_device(
                devices_by_customer,
                source.customer_id,
                rng,
            )
            transaction = Transaction(
                transaction_reference=transaction_reference,
                transfer_group_id=group.id,
                debit_account_id=source.id,
                credit_account_id=destination.id,
                merchant_id=None,
                device_id=device.id if device else None,
                transaction_type=TransactionType.INTERNAL,
                status=leg_statuses[leg_index],
                amount=amounts[leg_index],
                currency=DEFAULT_CURRENCY,
                occurred_at=occurred_at,
                description=f"Transfer leg {leg_index + 1} for {group.transfer_reference}",
                debit_account_status_snapshot=source.status,
                credit_account_status_snapshot=destination.status,
                created_at=occurred_at + timedelta(minutes=1),
                updated_at=occurred_at + timedelta(minutes=1),
            )
            transactions.append(transaction)
            if circular:
                labels[transaction_reference] = "CIRCULAR_FUND_TRANSFER"

    return groups, transactions, labels


def _build_pattern_transactions(
    profile: DatasetProfile,
    accounts: Sequence[Account],
    active_count: int,
    dormant_accounts: Sequence[Account],
    merchants: Sequence[Merchant],
    devices_by_customer: dict[int, list[Device]],
    tx_numbers: count,
    prefix: str,
    pattern_counts: dict[str, int],
) -> tuple[list[Transaction], dict[str, str]]:
    rng = _rng(profile, "patterns")
    active_merchants = [merchant for merchant in merchants if merchant.is_active]
    if not active_merchants:
        raise ValueError("At least one active merchant is required.")

    velocity_group_count, velocity_remainder = divmod(
        pattern_counts["HIGH_TRANSACTION_VELOCITY"],
        4,
    )
    repeated_group_count, repeated_remainder = divmod(
        pattern_counts["REPEATED_TRANSACTIONS"],
        3,
    )
    if velocity_remainder or repeated_remainder:
        raise ValueError("Velocity and repeated labels must form complete patterns.")

    if pattern_counts == PATTERN_COUNTS:
        reserved_active = list(accounts[active_count - 9 : active_count])
        if len(reserved_active) != 9:
            raise ValueError("Pattern account reservation failed.")
        velocity_accounts = [reserved_active[0]]
        repeated_accounts = [reserved_active[1]]
        high_value_accounts = reserved_active[2:6]
        new_device_accounts = reserved_active[6:9]
    else:
        active_candidates = list(accounts[: active_count - 9])
        new_device_accounts = []
        seen_customer_ids: set[int] = set()
        for account in active_candidates:
            if (
                account.customer_id not in seen_customer_ids
                and devices_by_customer.get(account.customer_id)
            ):
                new_device_accounts.append(account)
                seen_customer_ids.add(account.customer_id)
                if len(new_device_accounts) == pattern_counts["NEW_DEVICE_ACTIVITY"]:
                    break
        if len(new_device_accounts) != pattern_counts["NEW_DEVICE_ACTIVITY"]:
            raise ValueError("Not enough distinct active customers with devices.")

        used_account_ids = {account.id for account in new_device_accounts}
        remaining_accounts = [
            account
            for account in active_candidates
            if account.id not in used_account_ids
        ]
        high_value_end = pattern_counts["HIGH_VALUE_TRANSACTION"]
        repeated_end = high_value_end + repeated_group_count
        velocity_end = repeated_end + velocity_group_count
        if len(remaining_accounts) < velocity_end:
            raise ValueError("Not enough active accounts for positive-label patterns.")
        high_value_accounts = remaining_accounts[:high_value_end]
        repeated_accounts = remaining_accounts[high_value_end:repeated_end]
        velocity_accounts = remaining_accounts[repeated_end:velocity_end]

    dormant_count = pattern_counts["DORMANT_ACCOUNT_REACTIVATION"]
    if len(dormant_accounts) < dormant_count:
        raise ValueError("Not enough dormant accounts for positive-label patterns.")

    transactions: list[Transaction] = []
    labels: dict[str, str] = {}

    def make_transaction(
        account: Account,
        occurred_at: datetime,
        amount: Decimal,
        merchant: Merchant,
        device: Device | None,
        *,
        description: str,
        snapshot: AccountStatus | None = None,
    ) -> Transaction:
        transaction_reference = _reference(prefix, "TXN", next(tx_numbers), 6)
        transaction = Transaction(
            transaction_reference=transaction_reference,
            transfer_group_id=None,
            debit_account_id=account.id,
            credit_account_id=None,
            merchant_id=merchant.id,
            device_id=device.id if device else None,
            transaction_type=TransactionType.OUTGOING,
            status=TransactionStatus.POSTED,
            amount=amount,
            currency=DEFAULT_CURRENCY,
            occurred_at=occurred_at,
            description=description,
            debit_account_status_snapshot=snapshot or account.status,
            credit_account_status_snapshot=None,
            created_at=occurred_at + timedelta(minutes=1),
            updated_at=occurred_at + timedelta(minutes=1),
        )
        transactions.append(transaction)
        return transaction

    high_value_amounts = (
        Decimal("75000.00"),
        Decimal("95000.00"),
        Decimal("120000.00"),
        Decimal("150000.00"),
    )
    for index, account in enumerate(high_value_accounts):
        amount = high_value_amounts[index % len(high_value_amounts)]
        occurred_at = _at(
            profile.reference_datetime,
            days=20 + index,
            hours=5,
            minutes=index,
        )
        device = _trusted_device(devices_by_customer, account.customer_id, rng)
        transaction = make_transaction(
            account,
            occurred_at,
            amount,
            active_merchants[index % len(active_merchants)],
            device,
            description="High-value synthetic transaction",
        )
        labels[transaction.transaction_reference] = "HIGH_VALUE_TRANSACTION"

    for index, account in enumerate(new_device_accounts):
        devices = devices_by_customer.get(account.customer_id, [])
        if not devices:
            raise ValueError("New-device pattern requires a customer device.")
        device = devices[0]
        occurred_at = _at(
            profile.reference_datetime,
            days=25 + index,
            hours=6,
            minutes=index,
        )
        device.first_seen_at = occurred_at - timedelta(hours=3)
        device.last_seen_at = occurred_at + timedelta(hours=2)
        device.is_trusted = False
        device.updated_at = occurred_at
        transaction = make_transaction(
            account,
            occurred_at,
            _money(rng.randint(5000, 50000)),
            active_merchants[(index + 2) % len(active_merchants)],
            device,
            description="First transaction from a new device",
        )
        labels[transaction.transaction_reference] = "NEW_DEVICE_ACTIVITY"

    for index, account in enumerate(dormant_accounts[:dormant_count]):
        occurred_at = _at(
            profile.reference_datetime,
            days=30 + index,
            hours=7,
            minutes=index,
        )
        device = _trusted_device(devices_by_customer, account.customer_id, rng)
        transaction = make_transaction(
            account,
            occurred_at,
            _money(rng.randint(1000, 10000)),
            active_merchants[(index + 4) % len(active_merchants)],
            device,
            description="Reactivation of a dormant account",
            snapshot=AccountStatus.DORMANT,
        )
        labels[transaction.transaction_reference] = "DORMANT_ACCOUNT_REACTIVATION"

    repeated_merchant = active_merchants[0]
    repeated_amount = Decimal("1234.56")
    for repeated_account in repeated_accounts:
        repeated_device = _trusted_device(
            devices_by_customer,
            repeated_account.customer_id,
            rng,
        )
        for index in range(3):
            occurred_at = _at(
                profile.reference_datetime,
                days=15,
                hours=4,
                minutes=index * 2,
            )
            transaction = make_transaction(
                repeated_account,
                occurred_at,
                repeated_amount,
                repeated_merchant,
                repeated_device,
                description="Repeated synthetic transaction",
            )
            labels[transaction.transaction_reference] = "REPEATED_TRANSACTIONS"

    velocity_amounts = (
        Decimal("100.00"),
        Decimal("200.00"),
        Decimal("300.00"),
        Decimal("400.00"),
    )
    for velocity_account in velocity_accounts:
        velocity_device = _trusted_device(
            devices_by_customer,
            velocity_account.customer_id,
            rng,
        )
        for index, amount in enumerate(velocity_amounts):
            occurred_at = _at(
                profile.reference_datetime,
                days=10,
                hours=2,
                minutes=index * 5,
            )
            transaction = make_transaction(
                velocity_account,
                occurred_at,
                amount,
                active_merchants[(index + 6) % len(active_merchants)],
                velocity_device,
                description="Rapid synthetic transaction burst",
            )
            labels[transaction.transaction_reference] = "HIGH_TRANSACTION_VELOCITY"

    return transactions, labels


def _build_random_transactions(
    profile: DatasetProfile,
    accounts: Sequence[Account],
    active_count: int,
    merchants: Sequence[Merchant],
    devices_by_customer: dict[int, list[Device]],
    tx_numbers: count,
    count_needed: int,
    prefix: str,
) -> list[Transaction]:
    rng = _rng(profile, "transactions")
    active_merchants = [merchant for merchant in merchants if merchant.is_active]
    if not active_merchants:
        raise ValueError("At least one active merchant is required.")
    random_accounts = list(accounts[: active_count - 9])
    if len(random_accounts) < 2:
        raise ValueError("Not enough active accounts for random transactions.")
    transactions: list[Transaction] = []

    for index in range(count_needed):
        transaction_type = rng.choices(
            [
                TransactionType.OUTGOING,
                TransactionType.INCOMING,
                TransactionType.INTERNAL,
            ],
            weights=[60, 25, 15],
        )[0]
        occurred_at = _at(
            profile.reference_datetime,
            days=rng.randint(0, 89),
            seconds=rng.randint(0, 86399),
        )
        amount = _money(rng.randint(100, 500000))
        status = rng.choices(
            [
                TransactionStatus.POSTED,
                TransactionStatus.PENDING,
                TransactionStatus.FAILED,
                TransactionStatus.REVERSED,
            ],
            weights=[92, 3, 3, 2],
        )[0]

        debit_account: Account | None = None
        credit_account: Account | None = None
        if transaction_type is TransactionType.INTERNAL:
            debit_account, credit_account = rng.sample(random_accounts, 2)
        elif transaction_type is TransactionType.OUTGOING:
            debit_account = rng.choice(random_accounts)
        else:
            credit_account = rng.choice(random_accounts)

        account = debit_account or credit_account
        assert account is not None
        merchant: Merchant | None = None
        if transaction_type is not TransactionType.INTERNAL and rng.random() < 0.65:
            merchant = rng.choice(active_merchants)
        device = _trusted_device(devices_by_customer, account.customer_id, rng)
        transaction_reference = _reference(prefix, "TXN", next(tx_numbers), 6)

        transactions.append(
            Transaction(
                transaction_reference=transaction_reference,
                transfer_group_id=None,
                debit_account_id=debit_account.id if debit_account else None,
                credit_account_id=credit_account.id if credit_account else None,
                merchant_id=merchant.id if merchant else None,
                device_id=device.id if device else None,
                transaction_type=transaction_type,
                status=status,
                amount=amount,
                currency=DEFAULT_CURRENCY,
                occurred_at=occurred_at,
                description=f"Synthetic {transaction_type.value.lower()} transaction {index + 1}",
                debit_account_status_snapshot=(
                    debit_account.status if debit_account else None
                ),
                credit_account_status_snapshot=(
                    credit_account.status if credit_account else None
                ),
                created_at=occurred_at + timedelta(minutes=1),
                updated_at=occurred_at + timedelta(minutes=1),
            )
        )

    return transactions


def _apply_balances(
    accounts: Sequence[Account],
    transactions: Sequence[Transaction],
) -> None:
    balances = {account.id: OPENING_BALANCE for account in accounts}
    for transaction in transactions:
        if transaction.status != TransactionStatus.POSTED:
            continue
        if transaction.debit_account_id is not None:
            balances[transaction.debit_account_id] -= transaction.amount
        if transaction.credit_account_id is not None:
            balances[transaction.credit_account_id] += transaction.amount

    for account in accounts:
        balance = balances[account.id].quantize(Decimal("0.01"))
        if balance < -account.overdraft_limit:
            raise RuntimeError(
                f"Generated balance for {account.account_number} is below its overdraft."
            )
        account.balance = balance


def generate_dataset(
    profile: DatasetProfile,
    core_session: Session,
    eval_session: Session,
    *,
    run_reference: str | None = None,
) -> GenerationResult:
    """Generate one deterministic dataset and its isolated ground truth."""

    pattern_counts = pattern_counts_for_target(profile.target("positive_labels"))
    if profile.target("risk_rules") != len(RISK_RULES):
        raise ValueError("Risk-rule target does not match the rule catalogue.")

    run_reference = run_reference or profile.default_run_reference
    prefix = f"{run_reference}-"
    if core_session.scalar(
        select(DatasetRun.id).where(DatasetRun.run_reference == run_reference)
    ):
        raise ValueError(f"Dataset run {run_reference!r} already exists.")
    if eval_session.scalar(
        select(func.count())
        .select_from(GroundTruth)
        .where(GroundTruth.dataset_run_reference == run_reference)
    ):
        raise ValueError(
            f"Ground truth for dataset run {run_reference!r} already exists."
        )

    customers = _build_customers(profile, prefix)
    core_session.add_all(customers)
    core_session.flush()

    accounts, history, active_count, dormant_accounts = _build_accounts(
        profile,
        customers,
        prefix,
    )
    core_session.add_all(accounts)
    core_session.flush()
    core_session.add_all(history)

    devices = _build_devices(profile, customers, prefix)
    core_session.add_all(devices)
    core_session.flush()

    merchants = _build_merchants(profile, prefix)
    core_session.add_all(merchants)
    core_session.flush()

    rules = _upsert_risk_rules(core_session, profile)
    devices_by_customer: dict[int, list[Device]] = {}
    for device in devices:
        devices_by_customer.setdefault(device.customer_id, []).append(device)

    tx_numbers = count(1)
    groups, group_transactions, labels = _build_transfer_groups(
        profile,
        core_session,
        accounts,
        active_count,
        devices_by_customer,
        tx_numbers,
        prefix,
        pattern_counts,
    )
    pattern_transactions, pattern_labels = _build_pattern_transactions(
        profile,
        accounts,
        active_count,
        dormant_accounts,
        merchants,
        devices_by_customer,
        tx_numbers,
        prefix,
        pattern_counts,
    )
    labels.update(pattern_labels)

    transaction_target = profile.target("transactions")
    remaining = transaction_target - len(group_transactions) - len(pattern_transactions)
    if remaining < 0:
        raise ValueError("Transaction target is smaller than the reserved patterns.")
    random_transactions = _build_random_transactions(
        profile,
        accounts,
        active_count,
        merchants,
        devices_by_customer,
        tx_numbers,
        remaining,
        prefix,
    )

    transactions = [
        *group_transactions,
        *pattern_transactions,
        *random_transactions,
    ]
    if len(transactions) != transaction_target:
        raise RuntimeError("Generated transaction count does not match the target.")
    if len(groups) != profile.target("transfer_groups"):
        raise RuntimeError("Generated transfer-group count does not match the target.")

    core_session.add_all(transactions)
    core_session.flush()
    _apply_balances(accounts, transactions)
    core_session.flush()

    ground_truth: list[GroundTruth] = []
    for index, transaction in enumerate(transactions, start=1):
        pattern = labels.get(transaction.transaction_reference)
        ground_truth.append(
            GroundTruth(
                ground_truth_reference=_reference(prefix, "GT", index, 6),
                dataset_run_reference=run_reference,
                transaction_reference=transaction.transaction_reference,
                is_fraud=pattern is not None,
                primary_pattern=pattern,
                pattern_codes=[pattern] if pattern else [],
                label_source="SYNTHETIC_GENERATOR",
                generation_metadata={
                    "generator_version": GENERATOR_VERSION,
                    "profile": profile.name,
                    "seed": profile.seed,
                    "pattern": pattern,
                },
                created_at=profile.reference_datetime,
            )
        )
    eval_session.add_all(ground_truth)
    eval_session.flush()

    pattern_counter = Counter(
        row.primary_pattern for row in ground_truth if row.primary_pattern
    )
    pattern_count_dict = {
        pattern: pattern_counter.get(pattern, 0) for pattern in pattern_counts
    }
    if pattern_count_dict != pattern_counts:
        raise RuntimeError("Generated fraud-label distribution is incorrect.")

    risk_rule_count = int(
        core_session.scalar(select(func.count()).select_from(RiskRule)) or 0
    )
    counts: dict[str, Any] = {
        "customers": len(customers),
        "accounts": len(accounts),
        "account_status_history": len(history),
        "merchants": len(merchants),
        "devices": len(devices),
        "transfer_groups": len(groups),
        "transactions": len(transactions),
        "risk_rules": risk_rule_count,
        "dataset_runs": 1,
        "ground_truth": len(ground_truth),
        "ground_truth_positive": sum(pattern_count_dict.values()),
        "alerts": 0,
        "positive_labels_target": profile.target("positive_labels"),
        "fraud_labels_by_pattern": pattern_count_dict,
    }
    expected_counts = {
        "customers": profile.target("customers"),
        "accounts": profile.target("accounts"),
        "merchants": profile.target("merchants"),
        "devices": profile.target("devices"),
        "transfer_groups": profile.target("transfer_groups"),
        "transactions": profile.target("transactions"),
        "risk_rules": profile.target("risk_rules"),
    }
    for key, expected in expected_counts.items():
        if counts[key] != expected:
            raise RuntimeError(
                f"Generated {key} count {counts[key]} does not match {expected}."
            )
    if len(rules) != len(RISK_RULES):
        raise RuntimeError("Risk-rule upsert did not return the full catalogue.")

    checksums = compute_run_checksums(
        core_session,
        eval_session,
        run_reference=run_reference,
    )
    checksums["generator_version"] = GENERATOR_VERSION

    completed_at = utc_now()
    run = DatasetRun(
        run_reference=run_reference,
        profile_name=profile.name,
        seed=profile.seed,
        status=DatasetRunStatus.COMPLETED,
        reference_datetime_utc=profile.reference_datetime,
        record_counts=counts,
        checksums=checksums,
        started_at=completed_at,
        completed_at=completed_at,
    )
    core_session.add(run)
    core_session.flush()

    return GenerationResult(
        run=run,
        counts=counts,
        checksums=checksums,
        pattern_counts=pattern_count_dict,
    )
