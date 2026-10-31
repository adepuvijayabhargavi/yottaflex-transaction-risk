"""Validators for users, customers, merchants, and devices."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models import Customer, Device, Merchant, User
from app.models.enums import (
    CustomerRiskSegment,
    DeviceType,
    MerchantRiskLevel,
    UserRole,
)

from .base import (
    require,
    require_enum,
    require_non_blank,
    require_reference,
    require_timestamp,
    require_timestamp_order,
)


def validate_user(
    session: Session,
    user: User,
    *,
    record_event: bool = True,
) -> User:
    """Validate required user fields and role."""

    entity_type = "user"
    entity_id = user.id
    require_non_blank(
        user.username,
        session=session,
        field="username",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_non_blank(
        user.email,
        session=session,
        field="email",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_non_blank(
        user.password_hash,
        session=session,
        field="password_hash",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_non_blank(
        user.full_name,
        session=session,
        field="full_name",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_enum(
        user.role,
        UserRole,
        session=session,
        field="role",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    return user


def validate_customer(
    session: Session,
    customer: Customer,
    *,
    record_event: bool = True,
) -> Customer:
    """Validate customer identity, country, and risk segment."""

    entity_type = "customer"
    entity_id = customer.id
    require_non_blank(
        customer.customer_reference,
        session=session,
        field="customer_reference",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_non_blank(
        customer.first_name,
        session=session,
        field="first_name",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_non_blank(
        customer.last_name,
        session=session,
        field="last_name",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require(
        isinstance(customer.country_code, str) and len(customer.country_code) == 2,
        session=session,
        code="INVALID_COUNTRY_CODE",
        message="country_code must contain two characters",
        entity_type=entity_type,
        entity_id=entity_id,
        field="country_code",
        record_event=record_event,
    )
    require_enum(
        customer.risk_segment,
        CustomerRiskSegment,
        session=session,
        field="risk_segment",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require(
        isinstance(customer.onboarding_date, date),
        session=session,
        code="INVALID_DATE",
        message="onboarding_date must be a date",
        entity_type=entity_type,
        entity_id=entity_id,
        field="onboarding_date",
        record_event=record_event,
    )
    return customer


def validate_merchant(
    session: Session,
    merchant: Merchant,
    *,
    record_event: bool = True,
) -> Merchant:
    """Validate merchant identity, country, and risk level."""

    entity_type = "merchant"
    entity_id = merchant.id
    require_non_blank(
        merchant.merchant_reference,
        session=session,
        field="merchant_reference",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_non_blank(
        merchant.name,
        session=session,
        field="name",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require(
        isinstance(merchant.country_code, str) and len(merchant.country_code) == 2,
        session=session,
        code="INVALID_COUNTRY_CODE",
        message="country_code must contain two characters",
        entity_type=entity_type,
        entity_id=entity_id,
        field="country_code",
        record_event=record_event,
    )
    require_enum(
        merchant.risk_level,
        MerchantRiskLevel,
        session=session,
        field="risk_level",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    return merchant


def validate_device(
    session: Session,
    device: Device,
    *,
    record_event: bool = True,
) -> Device:
    """Validate device ownership, type, and observation timestamps."""

    entity_type = "device"
    entity_id = device.id
    require_non_blank(
        device.device_fingerprint,
        session=session,
        field="device_fingerprint",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_reference(
        session,
        Customer,
        device.customer_id,
        field="customer_id",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_enum(
        device.device_type,
        DeviceType,
        session=session,
        field="device_type",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_timestamp(
        device.first_seen_at,
        session=session,
        field="first_seen_at",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_timestamp(
        device.last_seen_at,
        session=session,
        field="last_seen_at",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    require_timestamp_order(
        device.first_seen_at,
        device.last_seen_at,
        session=session,
        earlier_field="first_seen_at",
        later_field="last_seen_at",
        entity_type=entity_type,
        entity_id=entity_id,
        record_event=record_event,
    )
    return device
