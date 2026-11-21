"""Small strict readers for values parsed from JSON. Each one returns a typed value or raises
SchemaError with the path of the offending field; nothing is ever coerced."""
from __future__ import annotations

import re

from xrpl.core.addresscodec import is_valid_classic_address

_LOWER_HEX = re.compile(r"[0-9a-f]*")
_TX_HASH = re.compile(r"[0-9A-F]{64}")


class SchemaError(ValueError):
    """A field is missing, unexpected, or has the wrong type or format."""


def obj(value: object, keys: set[str], where: str) -> dict[str, object]:
    """An object with exactly these keys."""
    if not isinstance(value, dict):
        raise SchemaError(f"{where}: expected an object")
    if set(value) != keys:
        extra, missing = sorted(set(value) - keys), sorted(keys - set(value))
        raise SchemaError(f"{where}: unexpected keys {extra}, missing keys {missing}")
    return value


def array(value: object, where: str) -> list[object]:
    if not isinstance(value, list):
        raise SchemaError(f"{where}: expected an array")
    return value


def integer(value: object, where: str, lo: int, hi: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise SchemaError(f"{where}: expected an integer in [{lo}, {hi}]")
    return value


def text(value: object, where: str, allowed: set[str] | None = None) -> str:
    if not isinstance(value, str) or (allowed is not None and value not in allowed):
        raise SchemaError(f"{where}: expected one of {sorted(allowed)}" if allowed else f"{where}: expected a string")
    return value


def hex_bytes(value: object, length: int, where: str) -> bytes:
    """Lowercase hex encoding exactly `length` bytes."""
    if not isinstance(value, str) or len(value) != 2 * length or not _LOWER_HEX.fullmatch(value):
        raise SchemaError(f"{where}: expected {length} bytes as lowercase hex")
    return bytes.fromhex(value)


def tx_hash(value: object, where: str) -> str:
    """An XRPL transaction hash: 64 uppercase hex characters."""
    if not isinstance(value, str) or not _TX_HASH.fullmatch(value):
        raise SchemaError(f"{where}: expected a transaction hash (64 uppercase hex)")
    return value


def address(value: object, where: str) -> str:
    if not isinstance(value, str) or not is_valid_classic_address(value):
        raise SchemaError(f"{where}: expected a classic XRPL address")
    return value
