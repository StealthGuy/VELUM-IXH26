"""The manifest: what the authority signs, once per image (docs/VELUM.md section 5).

    manifest = {"v": 1, "w": W, "h": H, "tile": 64, "root": hex, "authority": r-address, "pq_alg": "ML-DSA-44"}
    sig      = ML-DSA-44.Sign(sk, canonical(manifest), ctx = "VELUM/manifest/v1")
    memo     = SHA256(canonical(manifest)) || SHA256(sig)           anchored by the authority account
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from . import pq, schema
from .canonical import canonical_bytes
from .image import MAX_SIDE, size_problem
from .tiles import TILE

VERSION = 1
CTX = b"VELUM/manifest/v1"
MEMO_TYPE = "velum/manifest"
_KEYS = {"v", "w", "h", "tile", "root", "authority", "pq_alg"}


@dataclass(frozen=True)
class Manifest:
    width: int
    height: int
    root: bytes
    authority: str  # the authority's XRPL address

    def to_json(self) -> dict[str, object]:
        return {"v": VERSION, "w": self.width, "h": self.height, "tile": TILE, "root": self.root.hex(),
                "authority": self.authority, "pq_alg": pq.ALG}

    def canonical(self) -> bytes:
        return canonical_bytes(self.to_json())

    @classmethod
    def from_json(cls, value: object) -> Manifest:
        m = schema.obj(value, _KEYS, "manifest")
        schema.integer(m["v"], "manifest.v", VERSION, VERSION)
        schema.integer(m["tile"], "manifest.tile", TILE, TILE)
        schema.text(m["pq_alg"], "manifest.pq_alg", {pq.ALG})
        width = schema.integer(m["w"], "manifest.w", 1, MAX_SIDE)
        height = schema.integer(m["h"], "manifest.h", 1, MAX_SIDE)
        problem = size_problem(width, height)
        if problem:
            raise schema.SchemaError(f"manifest: {problem}")
        return cls(width=width, height=height,
                   root=schema.hex_bytes(m["root"], 32, "manifest.root"),
                   authority=schema.address(m["authority"], "manifest.authority"))


def sign(manifest: Manifest, sk: bytes, deterministic: bool = False) -> bytes:
    return pq.sign(sk, manifest.canonical(), CTX, deterministic)


def signature_ok(manifest: Manifest, pk: bytes, sig: bytes) -> bool:
    return pq.verify(pk, manifest.canonical(), sig, CTX)


def memo_data(manifest: Manifest, sig: bytes) -> bytes:
    """The 64 bytes the authority anchors on XRPL."""
    return hashlib.sha256(manifest.canonical()).digest() + hashlib.sha256(sig).digest()
