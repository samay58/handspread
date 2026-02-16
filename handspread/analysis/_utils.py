"""Shared utilities for analysis modules."""

from __future__ import annotations

from typing import Any


def extract_sec_value(sec_metrics: dict[str, Any], key: str) -> tuple[float | None, Any]:
    """Extract a numeric value and its source object from sec_metrics.

    Handles both single CitedValue and list[CitedValue] (from series queries).
    Returns (value, source_object) or (None, None) if missing.
    """
    cv = sec_metrics.get(key)
    if cv is None:
        return None, None
    if isinstance(cv, list):
        cv = cv[0] if cv else None
    if cv is None:
        return None, None
    return cv.value, cv
