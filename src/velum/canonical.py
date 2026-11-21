"""Canonical JSON: one byte string per value, the same in every language (docs/VELUM.md section 5).

Allowed values: printable-ASCII strings, integers, null, arrays and objects of the same.
No floats, no booleans. Keys sorted, no whitespace. Anything else is an error, never coerced.
"""
from __future__ import annotations

import json

MAX_DEPTH = 16  # VELUM documents nest at most 4 levels; a deeper one is hostile, not a sidecar


class CanonicalError(ValueError):
    """The value cannot be expressed in canonical JSON."""


def canonical_bytes(value: object) -> bytes:
    check(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def loads_strict(text: str) -> object:
    """Parse JSON refusing what canonical JSON forbids: non-integer numbers (1.0, 1e3), NaN/Infinity,
    duplicate keys, booleans, non-printable or escaped strings."""

    def no_float(token: str) -> object:
        raise CanonicalError(f"number {token!r} is not an integer")

    def no_constant(token: str) -> object:
        raise CanonicalError(f"{token} is not allowed")

    def unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        out: dict[str, object] = {}
        for key, item in pairs:
            if key in out:
                raise CanonicalError(f"duplicate key {key!r}")
            out[key] = item
        return out

    _check_depth(text)
    try:
        value = json.loads(text, parse_float=no_float, parse_constant=no_constant, object_pairs_hook=unique_keys)
    except CanonicalError:
        raise
    except json.JSONDecodeError as exc:
        raise CanonicalError(f"not valid JSON: {exc}") from exc
    except (ValueError, RecursionError) as exc:  # e.g. an integer above Python's 4300-digit limit
        raise CanonicalError(f"not acceptable JSON: {type(exc).__name__}: {exc}") from exc
    check(value)
    return value


def _check_depth(text: str) -> None:
    """Refuse nesting deeper than MAX_DEPTH before parsing, so hostile input cannot exhaust the stack."""
    depth, in_string, escaped = 0, False, False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch in "[{":
            depth += 1
            if depth > MAX_DEPTH:
                raise CanonicalError(f"JSON nested deeper than {MAX_DEPTH} levels")
        elif ch in "]}":
            depth -= 1


def check(value: object, path: str = "$") -> None:
    """Raise CanonicalError unless `value` uses only the allowed types."""
    if value is None:
        return
    if isinstance(value, bool):  # bool is a subclass of int in Python: reject it explicitly
        raise CanonicalError(f"{path}: booleans are not allowed")
    if isinstance(value, int):
        return
    if isinstance(value, str):
        _check_text(value, path)
        return
    if isinstance(value, list):
        for k, item in enumerate(value):
            check(item, f"{path}[{k}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalError(f"{path}: object keys must be strings")
            _check_text(key, f"{path} key")
            check(item, f"{path}.{key}")
        return
    raise CanonicalError(f"{path}: {type(value).__name__} is not allowed")


def _check_text(text: str, path: str) -> None:
    # printable ASCII only: no escapes, so every JSON encoder writes the same bytes
    if not all(0x20 <= ord(ch) <= 0x7E for ch in text) or '"' in text or "\\" in text:
        raise CanonicalError(f"{path}: strings must be printable ASCII without quotes or backslashes")
