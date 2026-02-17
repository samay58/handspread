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
    return getattr(cv, "value", None), cv


def infer_currency_from_unit(unit: str | None) -> str | None:
    """Extract currency code from a unit string.

    Examples:
    - "USD" -> "USD"
    - "JPY/shares" -> "JPY"
    - "shares" -> None
    - "pure" -> None
    """
    if not unit:
        return None

    cleaned = unit.strip()
    if not cleaned:
        return None

    lower = cleaned.lower()
    if lower in {"shares", "share", "pure", "ratio", "percent", "%"}:
        return None

    currency_part = cleaned.split("/", 1)[0].strip()
    if not currency_part:
        return None
    if currency_part.lower() in {"shares", "share", "pure", "ratio", "percent", "%"}:
        return None
    return currency_part.upper()


def infer_currency_from_source(source: Any) -> str | None:
    """Extract a currency code from an object that may have a .unit field."""
    if source is None:
        return None
    unit = getattr(source, "unit", None)
    if not isinstance(unit, str):
        return None
    return infer_currency_from_unit(unit)


def detect_sec_currency(
    sec_metrics: dict[str, Any],
    keys: tuple[str, ...] | None = None,
) -> str | None:
    """Return the first currency code found in SEC metric sources.

    If keys are provided, inspect only those metrics; otherwise inspect all.
    """
    metric_keys = keys if keys is not None else tuple(sec_metrics.keys())

    for key in metric_keys:
        source = sec_metrics.get(key)
        if source is None:
            continue
        if isinstance(source, list):
            for item in source:
                currency = infer_currency_from_source(item)
                if currency is not None:
                    return currency
            continue
        currency = infer_currency_from_source(source)
        if currency is not None:
            return currency

    return None


def cross_currency_warning(sec_currency: str, context: str) -> str:
    """Generate a consistent cross-currency warning message."""
    return (
        f"SEC data is in {sec_currency} but market data is in USD; "
        f"cannot mix currencies in {context}"
    )
