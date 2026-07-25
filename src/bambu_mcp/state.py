"""Sparse printer-report state handling."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def deep_merge(current: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    """Merge sparse MQTT reports without retaining references to caller data.

    Dictionaries merge recursively. Lists and scalar values are atomic because
    printer arrays (AMS trays, HMS faults, lights) are authoritative snapshots.
    """
    merged = deepcopy(current)
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged
