"""Test-only helpers: an independent PNG encoder that uses every row filter and real compression,
so the reader is tested on PNGs that VELUM's own writer would never produce."""
from __future__ import annotations

import struct
import zlib
from collections.abc import Sequence

SIGNATURE = b"\x89PNG\r\n\x1a\n"


def chunk(ctype: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + ctype + body + struct.pack(">I", zlib.crc32(ctype + body))


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def filter_row(ftype: int, line: bytes, prev: bytes, bpp: int) -> bytes:
    """Encode one row with filter `ftype` (the inverse of what the reader undoes)."""
    out = bytearray(len(line))
    for i, x in enumerate(line):
        a = line[i - bpp] if i >= bpp else 0
        b = prev[i]
        c = prev[i - bpp] if i >= bpp else 0
        pred = [0, a, b, (a + b) >> 1, _paeth(a, b, c)][ftype]
        out[i] = (x - pred) & 0xFF
    return bytes(out)


def encode_png(width: int, height: int, pixels: bytes, color_type: int = 2,
               filters: Sequence[int] = (0, 1, 2, 3, 4), level: int = 9,
               extra_chunks: Sequence[bytes] = (), depth: int = 8, interlace: int = 0) -> bytes:
    """PNG with row y using filters[y % len(filters)], zlib level `level`, split into two IDATs."""
    bpp = 3 if color_type == 2 else 4
    stride = width * bpp
    raw = bytearray()
    prev = bytes(stride)
    for y in range(height):
        line = pixels[y * stride:(y + 1) * stride]
        ftype = filters[y % len(filters)]
        raw += bytes([ftype]) + filter_row(ftype, line, prev, bpp)
        prev = line
    stream = zlib.compress(bytes(raw), level)
    half = len(stream) // 2
    ihdr = struct.pack(">IIBBBBB", width, height, depth, color_type, 0, 0, interlace)
    return (SIGNATURE + chunk(b"IHDR", ihdr) + b"".join(extra_chunks)
            + chunk(b"IDAT", stream[:half]) + chunk(b"IDAT", stream[half:]) + chunk(b"IEND", b""))


def gradient(width: int, height: int) -> bytes:
    """Deterministic RGB test pattern with every byte value represented."""
    return bytes(((x * 7 + y * 13 + ch * 101) ^ (x * y)) & 0xFF
                 for y in range(height) for x in range(width) for ch in range(3))
