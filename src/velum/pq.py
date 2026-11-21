"""ML-DSA-44 (FIPS 204) signatures via dilithium-py, with a FIPS 204 context string.

dilithium-py is pure Python and not constant-time: fine for a prototype; a real authority signs
inside an HSM or smartcard.
"""
from __future__ import annotations

import hashlib

from dilithium_py.ml_dsa import ML_DSA_44

ALG = "ML-DSA-44"
SEED_BYTES = 32
PK_BYTES = 1312
SIG_BYTES = 2420


def keypair(seed: bytes) -> tuple[bytes, bytes]:
    """(public key, secret key), derived deterministically from a 32-byte secret seed."""
    if len(seed) != SEED_BYTES:
        raise ValueError("ML-DSA seed must be 32 bytes")
    pk, sk = ML_DSA_44.key_derive(seed)
    return bytes(pk), bytes(sk)


def sign(sk: bytes, message: bytes, ctx: bytes, deterministic: bool = False) -> bytes:
    """Hedged (randomised) by default; `deterministic=True` only for reproducible test vectors."""
    return bytes(ML_DSA_44.sign(sk, message, ctx=ctx, deterministic=deterministic))


def verify(pk: bytes, message: bytes, sig: bytes, ctx: bytes) -> bool:
    """True only for a valid signature; malformed inputs, or any error inside the library, are False."""
    if len(pk) != PK_BYTES or len(sig) != SIG_BYTES:
        return False
    try:
        return bool(ML_DSA_44.verify(pk, message, sig, ctx=ctx))
    except Exception:  # fail closed: a crafted signature must never crash or pass the verifier
        return False


def fingerprint(pk: bytes) -> str:
    """SHA256(pk) in lowercase hex: the value a trust list pins."""
    return hashlib.sha256(pk).hexdigest()
