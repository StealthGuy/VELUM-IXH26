"""RFC 6962 Merkle Tree Hash over leaf hashes (docs/VELUM.md section 4).

The input is the list of *leaf hashes* (leaf_i = SHA256(0x00 || d_i)). They are never hashed again:
a hidden tile contributes exactly the 32 bytes found in the sidecar.

    MTH(one leaf)  = that leaf
    MTH(n > 1)     = SHA256(0x01 || MTH(first k) || MTH(the other n - k)),
                     k = the largest power of two strictly smaller than n
"""
from __future__ import annotations

import hashlib
from collections.abc import Sequence

HASH_BYTES = 32


def root(leaves: Sequence[bytes]) -> bytes:
    if not leaves:
        raise ValueError("a Merkle tree needs at least one leaf")
    if any(len(leaf) != HASH_BYTES for leaf in leaves):
        raise ValueError("every leaf hash must be 32 bytes")
    return _mth(list(leaves))


def _mth(leaves: list[bytes]) -> bytes:
    n = len(leaves)
    if n == 1:
        return leaves[0]
    k = 1 << ((n - 1).bit_length() - 1)  # largest power of two < n
    return hashlib.sha256(b"\x01" + _mth(leaves[:k]) + _mth(leaves[k:])).digest()
