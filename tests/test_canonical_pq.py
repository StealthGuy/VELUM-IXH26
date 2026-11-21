"""Canonical JSON (docs/VELUM.md section 5) and ML-DSA-44."""
from __future__ import annotations

import hashlib

import pytest

from velum import pq
from velum.canonical import CanonicalError, canonical_bytes, loads_strict


def test_canonical_json_is_sorted_and_compact() -> None:
    value = {"w": 1280, "root": "ab", "v": 1, "crop": None, "list": [3, -2, {"b": 1, "a": 2}]}
    assert canonical_bytes(value) == b'{"crop":null,"list":[3,-2,{"a":2,"b":1}],"root":"ab","v":1,"w":1280}'


@pytest.mark.parametrize("bad", [1.0, True, "café", "tab\there", 'quote"', "back\\slash",
                                 {1: "x"}, b"bytes", (1, 2)])
def test_canonical_json_rejects_anything_ambiguous(bad: object) -> None:
    with pytest.raises(CanonicalError):
        canonical_bytes({"x": bad})


def test_ml_dsa_keys_are_derived_from_the_seed() -> None:
    pk1, sk1 = pq.keypair(bytes(32))
    pk2, sk2 = pq.keypair(bytes(32))
    assert (pk1, sk1) == (pk2, sk2) and len(pk1) == pq.PK_BYTES
    assert pq.keypair(b"\x01" * 32)[0] != pk1
    with pytest.raises(ValueError):
        pq.keypair(b"short")


def test_ml_dsa_sign_and_verify_with_context() -> None:
    pk, sk = pq.keypair(bytes(32))
    sig = pq.sign(sk, b"manifest", b"VELUM/manifest/v1")
    assert len(sig) == pq.SIG_BYTES
    assert pq.verify(pk, b"manifest", sig, b"VELUM/manifest/v1")
    assert not pq.verify(pk, b"manifest", sig, b"VELUM/level/v1")  # other context
    assert not pq.verify(pk, b"manifesT", sig, b"VELUM/manifest/v1")  # other message
    assert not pq.verify(pq.keypair(b"\x02" * 32)[0], b"manifest", sig, b"VELUM/manifest/v1")
    assert not pq.verify(pk, b"manifest", sig[:-1], b"VELUM/manifest/v1")  # malformed: False, no crash
    assert pq.fingerprint(pk) == hashlib.sha256(pk).hexdigest()


# ---------------------------------------------------------------- audit fixes: hostile JSON is an error
@pytest.mark.parametrize("text", ["[" * 100_000 + "]" * 100_000, '{"a":' + "9" * 5000 + "}",
                                  "[" * 17 + "]" * 17])
def test_hostile_json_raises_canonical_error(text: str) -> None:
    with pytest.raises(CanonicalError):
        loads_strict(text)


def test_brackets_inside_strings_do_not_count_as_nesting() -> None:
    assert loads_strict('{"a":"[[[[[[[[[[[[[[[[[[[[","b":[[1]]}') == {"a": "[" * 20, "b": [[1]]}
