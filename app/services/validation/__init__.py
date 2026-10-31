"""Edge-case and data-integrity validation services."""

from .accounts import (
    ALLOWED_ACCOUNT_STATUS_TRANSITIONS,
    validate_account,
    validate_account_balance,
    validate_account_status_history,
    validate_account_status_transition,
)
from .base import (
    require_reference,
    validate_primary_key_reference,
)
from .cases import (
    validate_case,
    validate_case_alert,
    validate_case_decision,
    validate_case_note,
)
from .errors import ValidationError, ValidationIssue
from .operations import (
    validate_audit_event,
    validate_dataset_run,
    validate_validation_event,
)
from .parties import (
    validate_customer,
    validate_device,
    validate_merchant,
    validate_user,
)
from .recording import record_validation_issue
from .risk import (
    validate_alert,
    validate_risk_assessment,
    validate_risk_finding,
    validate_risk_rule,
)
from .transactions import validate_transaction
from .transfers import validate_transfer_group

__all__ = [
    "ALLOWED_ACCOUNT_STATUS_TRANSITIONS",
    "ValidationError",
    "ValidationIssue",
    "record_validation_issue",
    "require_reference",
    "validate_account",
    "validate_account_balance",
    "validate_account_status_history",
    "validate_account_status_transition",
    "validate_alert",
    "validate_audit_event",
    "validate_case",
    "validate_case_alert",
    "validate_case_decision",
    "validate_case_note",
    "validate_customer",
    "validate_dataset_run",
    "validate_device",
    "validate_merchant",
    "validate_primary_key_reference",
    "validate_risk_assessment",
    "validate_risk_finding",
    "validate_risk_rule",
    "validate_transaction",
    "validate_transfer_group",
    "validate_user",
    "validate_validation_event",
]
