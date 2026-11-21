"""Tile grid, salts and leaf hashes (docs/VELUM.md sections 3 and 4).

    salt_i = HMAC-SHA256(K, "VELUM/salt/v1" || u32be(i))
    d_i    = "VELUM/leaf/v1" || u32be(i) || salt_i || tile_i        (tile_i zero padded to 64x64)
    leaf_i = SHA256(0x00 || d_i)                                    the RFC 6962 leaf hash of d_i
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from .image import Image

TILE = 64
TILE_BYTES = TILE * TILE * 3  # 12 288
SALT_BYTES = 32
SECRET_BYTES = 32  # K
LEAF_TAG = b"VELUM/leaf/v1"
SALT_TAG = b"VELUM/salt/v1"


def u32be(i: int) -> bytes:
    return i.to_bytes(4, "big")


@dataclass(frozen=True)
class Grid:
    """The 64-pixel tile grid over a W x H image. Tile i = row * cols + col."""

    width: int
    height: int

    @property
    def cols(self) -> int:
        return -(-self.width // TILE)  # ceil(width / 64)

    @property
    def rows(self) -> int:
        return -(-self.height // TILE)

    @property
    def n(self) -> int:
        return self.cols * self.rows

    def rect(self, i: int) -> tuple[int, int, int, int]:
        """(x0, y0, w, h) of the *real* pixels of tile i; edge tiles are smaller than 64 x 64."""
        if not 0 <= i < self.n:
            raise IndexError(f"tile {i} outside 0..{self.n - 1}")
        x0, y0 = (i % self.cols) * TILE, (i // self.cols) * TILE
        return x0, y0, min(TILE, self.width - x0), min(TILE, self.height - y0)


def grid_of(image: Image) -> Grid:
    return Grid(image.width, image.height)


def tile_bytes(image: Image, i: int) -> bytes:
    """The 64 x 64 x 3 bytes of tile i. Padding (pixels outside the image) is always zero,
    synthesised here and never read from any file (docs/VELUM.md section 8.1)."""
    x0, y0, w, h = grid_of(image).rect(i)
    pad = bytes((TILE - w) * 3)
    out = bytearray()
    for y in range(y0, y0 + h):
        start = (y * image.width + x0) * 3
        out += image.rgb[start:start + w * 3] + pad
    out += bytes((TILE - h) * TILE * 3)
    return bytes(out)


def derive_salt(secret: bytes, i: int) -> bytes:
    if len(secret) != SECRET_BYTES:
        raise ValueError("salt secret K must be 32 bytes")
    return hmac.new(secret, SALT_TAG + u32be(i), hashlib.sha256).digest()


def leaf_entry(i: int, salt: bytes, tile: bytes) -> bytes:
    """d_i, the RFC 6962 entry of tile i."""
    if len(salt) != SALT_BYTES or len(tile) != TILE_BYTES:
        raise ValueError("bad salt or tile length")
    return LEAF_TAG + u32be(i) + salt + tile


def leaf_hash(i: int, salt: bytes, tile: bytes) -> bytes:
    """leaf_i = SHA256(0x00 || d_i)."""
    return hashlib.sha256(b"\x00" + leaf_entry(i, salt, tile)).digest()


def all_leaves(image: Image, secret: bytes) -> list[bytes]:
    """Authority side: the leaf hash of every tile of the original image."""
    return [leaf_hash(i, derive_salt(secret, i), tile_bytes(image, i)) for i in range(grid_of(image).n)]
