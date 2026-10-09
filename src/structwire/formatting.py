"""Optional human-readable formatting helpers."""

from __future__ import annotations

from typing import Any


def format_mac_address(data: bytes | bytearray | memoryview, *, byteorder: str = "big") -> str:
    """Format six address bytes as uppercase, colon-separated hexadecimal."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise ValueError("MAC address must be bytes, bytearray or memoryview")
    raw = bytes(data)
    if len(raw) != 6:
        raise ValueError("MAC address requires exactly six bytes")
    if byteorder == "little":
        raw = raw[::-1]
    elif byteorder != "big":
        raise ValueError("byteorder must be 'big' or 'little'")
    return ":".join(f"{value:02X}" for value in raw)


def format_value(value: Any) -> Any:
    """Recursively format byte strings as uppercase, space-separated hex."""
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        return "<empty>" if not raw else raw.hex(" ").upper()
    if isinstance(value, dict):
        return {key: format_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [format_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(format_value(item) for item in value)
    return value


def format_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return a new record with bytes formatted recursively by :func:`format_value`."""
    return {key: format_value(value) for key, value in record.items()}
