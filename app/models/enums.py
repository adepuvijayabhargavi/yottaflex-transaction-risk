"""Enumerations shared by the core database models."""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Enum as SAEnum


class UserRole(StrEnum):
    ADMIN = "ADMIN"
    ANALYST = "ANALYST"
    SUPERVISOR = "SUPERVISOR"


class CustomerRiskSegment(StrEnum):
    LOW = "LOW"
    STANDARD = "STANDARD"
    HIGH = "HIGH"


class CurrencyCode(StrEnum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    INR = "INR"
    AED = "AED"


class AccountType(StrEnum):
    CHECKING = "CHECKING"
    SAVINGS = "SAVINGS"
    BUSINESS = "BUSINESS"
    WALLET = "WALLET"


class AccountStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DORMANT = "DORMANT"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class MerchantRiskLevel(StrEnum):
    LOW = "LOW"
    STANDARD = "STANDARD"
    HIGH = "HIGH"


class DeviceType(StrEnum):
    MOBILE = "MOBILE"
    TABLET = "TABLET"
    DESKTOP = "DESKTOP"
    UNKNOWN = "UNKNOWN"


class TransferStatus(StrEnum):
    PENDING = "PENDING"
    RECONCILED = "RECONCILED"
    FAILED = "FAILED"


class TransactionType(StrEnum):
    OUTGOING = "OUTGOING"
    INCOMING = "INCOMING"
    INTERNAL = "INTERNAL"


class TransactionStatus(StrEnum):
    PENDING = "PENDING"
    POSTED = "POSTED"
    FAILED = "FAILED"
    REVERSED = "REVERSED"


class RiskSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AssessmentStatus(StrEnum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AlertStatus(StrEnum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CLOSED = "CLOSED"
    DISMISSED = "DISMISSED"


class AlertPriority(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class CaseStatus(StrEnum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"


class CasePriority(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class CaseNoteType(StrEnum):
    GENERAL = "GENERAL"
    INVESTIGATION = "INVESTIGATION"
    ESCALATION = "ESCALATION"
    SYSTEM = "SYSTEM"


class CaseDecisionType(StrEnum):
    NO_ACTION = "NO_ACTION"
    MONITOR = "MONITOR"
    ESCALATE = "ESCALATE"
    CONFIRM_FRAUD = "CONFIRM_FRAUD"
    CLEAR = "CLEAR"


class DatasetRunStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ValidationSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class ValidationResolutionStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    WAIVED = "WAIVED"


def enum_type(enum_class: type[StrEnum], name: str) -> SAEnum:
    """Build a portable enum column that stores member values."""

    return SAEnum(
        enum_class,
        name=name,
        values_callable=lambda member: [item.value for item in member],
        validate_strings=True,
    )
