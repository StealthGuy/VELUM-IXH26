"""Level descriptor: what the producer of a redacted copy anchors (docs/VELUM.md section 6.1).

    descriptor = {"v": 1, "manifest_tx": TX, "producer": r-address,
                  "hidden": hex bitmap, "crop": [col0, row0, cols, rows] | null,
                  "recipe": {"rotate", "resize", "brightness", "contrast"} | null}
    memo       = SHA256(canonical(descriptor))                      anchored by the producer account

The hidden bitmap has ceil(n/8) bytes, MSB first: tile i is bit 7 - (i % 8) of byte i // 8.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from . import schema
from .canonical import canonical_bytes
from .image import MAX_SIDE

VERSION = 1
MEMO_TYPE = "velum/level"
ROTATIONS = (0, 90, 180, 270)
_KEYS = {"v", "manifest_tx", "producer", "hidden", "crop", "recipe"}
_RECIPE_KEYS = {"rotate", "resize", "brightness", "contrast"}


# ---------------------------------------------------------------- hidden bitmap
def encode_bitmap(hidden: frozenset[int], n: int) -> str:
    out = bytearray((n + 7) // 8)
    for i in hidden:
        if not 0 <= i < n:
            raise ValueError(f"tile {i} outside 0..{n - 1}")
        out[i // 8] |= 0x80 >> (i % 8)
    return out.hex()


def decode_bitmap(value: str, n: int, where: str) -> frozenset[int]:
    data = schema.hex_bytes(value, (n + 7) // 8, where)
    hidden = frozenset(i for i in range(len(data) * 8) if data[i // 8] & (0x80 >> (i % 8)))
    if any(i >= n for i in hidden):
        raise schema.SchemaError(f"{where}: bits set beyond tile {n - 1}")
    return hidden


# ---------------------------------------------------------------- recipe
@dataclass(frozen=True)
class Recipe:
    """Public rendition recipe (docs/VELUM.md section 6.4). The defaults are the identity."""

    rotate: int = 0
    resize: tuple[int, int] | None = None
    brightness: int = 0
    contrast: int = 0

    def __post_init__(self) -> None:
        if self.rotate not in ROTATIONS:
            raise ValueError("rotate must be 0, 90, 180 or 270")
        if not (-255 <= self.brightness <= 255 and -255 <= self.contrast <= 255):
            raise ValueError("brightness and contrast must be in [-255, 255]")
        if self.resize is not None and not all(1 <= v <= MAX_SIDE for v in self.resize):
            raise ValueError("resize target out of range")

    def to_json(self) -> dict[str, object]:
        return {"rotate": self.rotate, "resize": list(self.resize) if self.resize else None,
                "brightness": self.brightness, "contrast": self.contrast}

    @classmethod
    def from_json(cls, value: object, where: str) -> Recipe:
        r = schema.obj(value, _RECIPE_KEYS, where)
        rotate = schema.integer(r["rotate"], f"{where}.rotate", 0, 270)
        if rotate not in ROTATIONS:
            raise schema.SchemaError(f"{where}.rotate: must be 0, 90, 180 or 270")
        resize = None
        if r["resize"] is not None:
            pair = schema.array(r["resize"], f"{where}.resize")
            if len(pair) != 2:
                raise schema.SchemaError(f"{where}.resize: expected [width, height]")
            resize = (schema.integer(pair[0], f"{where}.resize[0]", 1, MAX_SIDE),
                      schema.integer(pair[1], f"{where}.resize[1]", 1, MAX_SIDE))
        return cls(rotate=rotate, resize=resize,
                   brightness=schema.integer(r["brightness"], f"{where}.brightness", -255, 255),
                   contrast=schema.integer(r["contrast"], f"{where}.contrast", -255, 255))


# ---------------------------------------------------------------- descriptor
@dataclass(frozen=True)
class Descriptor:
    manifest_tx: str
    producer: str  # the XRPL account that anchors this descriptor
    n: int  # tile count, from the manifest (not serialised: the bitmap length depends on it)
    hidden: frozenset[int]
    crop: tuple[int, int, int, int] | None = None  # col0, row0, cols, rows (tile units)
    recipe: Recipe | None = None

    def __post_init__(self) -> None:
        outside = sorted(i for i in self.hidden if not 0 <= i < self.n)
        if outside:
            raise ValueError(f"hidden tiles {outside} outside 0..{self.n - 1}")

    def to_json(self) -> dict[str, object]:
        return {"v": VERSION, "manifest_tx": self.manifest_tx, "producer": self.producer,
                "hidden": encode_bitmap(self.hidden, self.n),
                "crop": list(self.crop) if self.crop else None,
                "recipe": self.recipe.to_json() if self.recipe else None}

    def canonical(self) -> bytes:
        return canonical_bytes(self.to_json())

    def memo_data(self) -> bytes:
        """The 32 bytes the producer anchors on XRPL."""
        return hashlib.sha256(self.canonical()).digest()

    @classmethod
    def from_json(cls, value: object, n: int, where: str) -> Descriptor:
        d = schema.obj(value, _KEYS, where)
        schema.integer(d["v"], f"{where}.v", VERSION, VERSION)
        crop = None
        if d["crop"] is not None:
            cells = schema.array(d["crop"], f"{where}.crop")
            if len(cells) != 4:
                raise schema.SchemaError(f"{where}.crop: expected [col0, row0, cols, rows]")
            c0, r0, cs, rs = (schema.integer(v, f"{where}.crop[{k}]", 0, MAX_SIDE) for k, v in enumerate(cells))
            crop = (c0, r0, cs, rs)
        return cls(manifest_tx=schema.tx_hash(d["manifest_tx"], f"{where}.manifest_tx"),
                   producer=schema.address(d["producer"], f"{where}.producer"),
                   n=n, hidden=decode_bitmap(schema.text(d["hidden"], f"{where}.hidden"), n, f"{where}.hidden"),
                   crop=crop,
                   recipe=None if d["recipe"] is None else Recipe.from_json(d["recipe"], f"{where}.recipe"))
