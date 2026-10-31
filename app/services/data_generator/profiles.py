"""Dataset profile loading and validation."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROFILES_DIRECTORY = Path(__file__).resolve().parents[3] / "dataset_profiles"
_PROFILE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_REQUIRED_TARGETS = {
    "customers",
    "accounts",
    "merchants",
    "devices",
    "transfer_groups",
    "transactions",
    "alerts",
    "risk_rules",
}


@dataclass(frozen=True, slots=True)
class DatasetProfile:
    """A deterministic dataset profile from `dataset_profiles`."""

    name: str
    seed: int
    reference_datetime: datetime
    targets: Mapping[str, int]

    @property
    def default_run_reference(self) -> str:
        """Return the stable reference used for a profile and seed."""

        return f"{self.name.upper()}-{self.seed}"

    def target(self, table_name: str) -> int:
        """Return one required target count."""

        try:
            return self.targets[table_name]
        except KeyError as exc:
            raise KeyError(
                f"Profile {self.name!r} has no target for {table_name!r}."
            ) from exc


def _parse_reference_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(UTC).replace(tzinfo=None)


def load_profile(name: str, *, seed: int | None = None) -> DatasetProfile:
    """Load and validate a dataset profile by name."""

    if not _PROFILE_NAME_PATTERN.fullmatch(name):
        raise ValueError(f"Invalid dataset profile name: {name!r}.")
    path = PROFILES_DIRECTORY / f"{name}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Dataset profile not found: {path}.")

    with path.open(encoding="utf-8") as handle:
        payload: dict[str, Any] = json.load(handle)

    raw_targets = payload.get("targets")
    if not isinstance(raw_targets, dict):
        raise TypeError(f"Dataset profile {name!r} must contain a targets object.")
    if set(raw_targets) != _REQUIRED_TARGETS:
        missing = sorted(_REQUIRED_TARGETS - set(raw_targets))
        extra = sorted(set(raw_targets) - _REQUIRED_TARGETS)
        raise ValueError(
            f"Dataset profile {name!r} target mismatch. "
            f"Missing={missing}; extra={extra}."
        )

    targets: dict[str, int] = {}
    for key, value in raw_targets.items():
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(
                f"Dataset profile {name!r} target {key!r} must be a non-negative integer."
            )
        targets[key] = value

    profile_seed = payload.get("seed") if seed is None else seed
    if not isinstance(profile_seed, int) or isinstance(profile_seed, bool):
        raise TypeError(f"Dataset profile {name!r} seed must be an integer.")
    if not isinstance(payload.get("profile"), str):
        raise TypeError(f"Dataset profile {name!r} must contain a profile name.")
    if not isinstance(payload.get("reference_datetime_utc"), str):
        raise TypeError(
            f"Dataset profile {name!r} must contain reference_datetime_utc."
        )

    return DatasetProfile(
        name=payload["profile"],
        seed=profile_seed,
        reference_datetime=_parse_reference_datetime(payload["reference_datetime_utc"]),
        targets=targets,
    )
