"""New device activity detection rule."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models import Device, Transaction

from .base import BaseRiskRule, RuleMatch


class NewDeviceActivityRule(BaseRiskRule):
    """Detects transactions originating from new or untrusted devices."""

    def evaluate(self, session: Session, transaction: Transaction) -> RuleMatch | None:
        if transaction.device_id is None:
            return None

        device = (
            transaction.device
            if getattr(transaction, "device", None) is not None
            else session.get(Device, transaction.device_id)
        )
        if device is None:
            return None

        require_untrusted = bool(self.configuration.get("require_untrusted", True))
        if require_untrusted and device.is_trusted:
            return None

        device_age_hours = float(self.configuration.get("device_age_hours", 24))
        max_age = timedelta(hours=device_age_hours)

        age = transaction.occurred_at - device.first_seen_at
        if age < timedelta(0) or age > max_age:
            return None

        age_hours = round(age.total_seconds() / 3600, 2)
        evidence: dict[str, Any] = {
            "device_id": device.id,
            "device_fingerprint": device.device_fingerprint,
            "device_age_hours": age_hours,
            "threshold_hours": device_age_hours,
            "is_trusted": device.is_trusted,
            "first_seen_at": (
                device.first_seen_at.isoformat() if device.first_seen_at else None
            ),
        }
        explanation = (
            f"Transaction from a new untrusted device first seen {age_hours} hours prior "
            f"(threshold: {device_age_hours} hours)"
        )
        return RuleMatch(
            rule_code=self.code,
            score=self.weight,
            severity=self.severity,
            explanation=explanation,
            evidence=evidence,
        )
