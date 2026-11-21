"""Minimal PNG reader and writer, standard library only (docs/VELUM.md section 3).

Reader: any valid PNG with bit depth 8, colour type 2 (RGB) or 6 (RGBA with every alpha = 255),
no interlace, any compression and any row filter. CRCs are checked, ancillary chunks ignored,
anything else rejected. Verification compares decoded pixels, so this is the part that matters.
With `strict=True` (what the verifier uses) only ancillary chunks that no viewer turns into pixels are
allowed: APNG frames, tRNS, colour profiles or eXIf would make a browser show something other than the
verified pixels (docs/VELUM.md section 3). `max_pixels` lowers the size limit, checked before inflating.

Writer: uncompressed PNG (zlib "stored" blocks, filter 0 on every row), chunks IHDR, IDAT, IEND, plus
optionally one zTXt chunk "velum.sidecar" carrying the sidecar JSON (docs/VELUM.md section 6).
"""
from __future__ import annotations

import struct
import zlib
from collections.abc import Iterator

from .image import Image, size_problem

SIGNATURE = b"\x89PNG\r\n\x1a\n"
COLOR_RGB = 2
COLOR_RGBA = 6
_STORED_BLOCK_MAX = 65535  # largest deflate stored block
SIDECAR_KEYWORD = b"velum.sidecar"
MAX_SIDECAR = 4 << 20  # bytes once inflated; a 2^25-pixel image needs well under 1 MiB
# ancillary chunks that only carry text or a time: what a viewer displays does not depend on them
DISPLAY_SAFE = frozenset({b"tEXt", b"zTXt", b"iTXt", b"tIME"})


class PngError(ValueError):
    """The bytes are not a PNG that VELUM accepts."""


class OverBudget(PngError):
    """The image is valid but larger than this reader was asked to process: says nothing about authenticity."""


class SidecarError(PngError):
    """The PNG is readable but its velum.sidecar chunk is not (duplicate, bad compression, not ASCII,
    too large). Never a reason to fall back to an external sidecar file."""


# ---------------------------------------------------------------- reading
def read_png(data: bytes, strict: bool = False, max_pixels: int | None = None) -> Image:
    width, height, color_type, idat = _parse_chunks(data, strict, max_pixels)
    bpp = 3 if color_type == COLOR_RGB else 4  # bytes per pixel
    expected = height * (1 + width * bpp)  # one filter byte per row
    raw = _inflate_exactly(idat, expected)
    pixels = _unfilter(raw, width, height, bpp)
    if color_type == COLOR_RGBA:
        pixels = _drop_opaque_alpha(pixels)
    return Image(width, height, bytes(pixels))


def _chunks(data: bytes) -> Iterator[tuple[bytes, bytes]]:
    """Every (type, body) from the signature to IEND, CRCs checked; nothing may follow IEND."""
    if not data.startswith(SIGNATURE):
        raise PngError("not a PNG (bad signature)")
    pos = len(SIGNATURE)
    while True:
        if pos + 12 > len(data):
            raise PngError("truncated chunk")
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if len(body) != length or pos + 12 + length > len(data):
            raise PngError("truncated chunk")
        (crc,) = struct.unpack(">I", data[pos + 8 + length:pos + 12 + length])
        if zlib.crc32(ctype + body) != crc:
            raise PngError(f"bad CRC in {ctype!r} chunk")
        pos += 12 + length
        yield ctype, body
        if ctype == b"IEND":
            break
    if pos != len(data):
        raise PngError("data after IEND")


def _parse_chunks(data: bytes, strict: bool = False, max_pixels: int | None = None) -> tuple[int, int, int, bytes]:
    """Return (width, height, colour type, concatenated IDAT data)."""
    header: tuple[int, int, int] | None = None
    idat = bytearray()
    idat_closed = False  # IDAT chunks must be consecutive (PNG spec; libpng and browsers enforce it)
    for ctype, body in _chunks(data):
        if header is None and ctype != b"IHDR":
            raise PngError("IHDR must be the first chunk")
        if ctype == b"IDAT" and idat_closed:
            raise PngError("IDAT chunks are not consecutive")
        if ctype != b"IDAT" and idat:
            idat_closed = True
        if ctype == b"IHDR":
            if header is not None:
                raise PngError("duplicate IHDR")
            header = _parse_ihdr(body)
            if max_pixels is not None and header[0] * header[1] > max_pixels:
                raise OverBudget(f"image is {header[0]}x{header[1]}, above this verifier's budget of {max_pixels} "
                               "pixels")
        elif ctype == b"IDAT":
            idat += body
        elif ctype == b"IEND":
            pass
        elif ctype == b"PLTE":  # allowed for truecolour as a palette suggestion; pixels do not use it
            if strict:
                raise PngError("PLTE chunk not allowed: a viewer may display the image through it")
        elif not ctype[0] & 0x20:  # uppercase first letter = critical chunk we do not know
            raise PngError(f"unsupported critical chunk {ctype!r}")
        elif strict and ctype not in DISPLAY_SAFE:
            raise PngError(f"{ctype.decode('latin-1')!r} chunk not allowed: it can change what a viewer displays "
                           "(only tEXt, zTXt, iTXt, tIME may be added to a VELUM image)")
        # other lowercase first letter = ancillary (gAMA, iCCP, tEXt, zTXt, ...): ignored for the pixels
    if header is None or not idat:
        raise PngError("missing IHDR or IDAT")
    width, height, color_type = header
    return width, height, color_type, bytes(idat)


def read_sidecar(data: bytes) -> str | None:
    """The sidecar JSON embedded in a zTXt chunk "velum.sidecar", or None if there is none.
    Raises PngError if the bytes are not a readable PNG, SidecarError if the chunk itself is bad.
    Two such chunks are an error: which one would count?"""
    found: str | None = None
    for ctype, body in _chunks(data):
        if ctype == b"zTXt" and body.startswith(SIDECAR_KEYWORD + b"\x00"):
            if found is not None:
                raise SidecarError("more than one velum.sidecar chunk")
            rest = body[len(SIDECAR_KEYWORD) + 1:]
            if not rest or rest[0] != 0:
                raise SidecarError("velum.sidecar: unknown compression method")
            try:
                text = _inflate_at_most(rest[1:], MAX_SIDECAR)
            except PngError as exc:
                raise SidecarError(f"velum.sidecar: {exc}") from exc
            try:
                found = text.decode("ascii")
            except UnicodeDecodeError as exc:
                raise SidecarError("velum.sidecar is not ASCII") from exc
    return found


def _parse_ihdr(body: bytes) -> tuple[int, int, int]:
    if len(body) != 13:
        raise PngError("bad IHDR length")
    width, height, depth, color_type, compression, filtering, interlace = struct.unpack(">IIBBBBB", body)
    problem = size_problem(width, height)  # checked before anything is inflated
    if problem:
        raise PngError(problem)
    if depth != 8:
        raise PngError(f"bit depth {depth} not supported (only 8)")
    if color_type not in (COLOR_RGB, COLOR_RGBA):
        raise PngError(f"colour type {color_type} not supported (only RGB or RGBA)")
    if compression != 0 or filtering != 0:
        raise PngError("unknown compression or filter method")
    if interlace != 0:
        raise PngError("interlaced PNG not supported")
    return width, height, color_type


def _inflate_at_most(stream: bytes, limit: int) -> bytes:
    d = zlib.decompressobj()
    try:
        out = d.decompress(stream, limit + 1)
    except zlib.error as exc:
        raise PngError(f"corrupt compressed text: {exc}") from exc
    if len(out) > limit or not d.eof or d.unconsumed_tail or d.unused_data:
        raise PngError("compressed text too large or malformed")
    return out


def _inflate_exactly(stream: bytes, expected: int) -> bytes:
    """Decompress the zlib stream, refusing anything but exactly `expected` bytes (no zip bombs)."""
    d = zlib.decompressobj()
    try:
        out = d.decompress(stream, expected + 1)  # never inflate more than one byte past the limit
    except zlib.error as exc:
        raise PngError(f"corrupt image data: {exc}") from exc
    if len(out) != expected or not d.eof or d.unconsumed_tail or d.unused_data:
        raise PngError("image data has the wrong size")
    return out


def _unfilter(raw: bytes, width: int, height: int, bpp: int) -> bytearray:
    """Undo the per-row PNG filters 0-4 (None, Sub, Up, Average, Paeth). All arithmetic mod 256."""
    stride = width * bpp
    out = bytearray(height * stride)
    prev = bytearray(stride)  # the row above the first row is all zeros
    pos = 0
    for y in range(height):
        ftype = raw[pos]
        line = bytearray(raw[pos + 1:pos + 1 + stride])
        pos += 1 + stride
        if ftype == 0:  # None
            pass
        elif ftype == 2 and y > 0:  # Up, as one byte-wise addition of two whole rows (fast path)
            line = _add_bytes(line, prev)
        elif ftype == 1:  # Sub: add the byte one pixel to the left
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ftype == 2:  # Up: add the byte above
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:  # Average: add floor((left + above) / 2)
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:  # Paeth: add whichever of left, above, upper-left is closest to left+above-upper_left
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                predictor = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                line[i] = (line[i] + predictor) & 0xFF
        else:
            raise PngError(f"unknown filter type {ftype} in row {y}")
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return out


_HIGH: dict[int, int] = {}


def _add_bytes(a: bytearray, b: bytearray) -> bytearray:
    """(a[i] + b[i]) mod 256 for every i, on two equally long rows, without a Python loop per byte:
    add the low 7 bits of every byte as one big integer (no carry crosses a byte), then put back the
    top bit of each sum with XOR."""
    n = len(a)
    high = _HIGH.get(n)
    if high is None:
        high = _HIGH[n] = int.from_bytes(b"\x80" * n, "big")
    low = high ^ ((1 << (8 * n)) - 1)
    x, y = int.from_bytes(a, "big"), int.from_bytes(b, "big")
    s = ((x & low) + (y & low)) ^ ((x ^ y) & high)
    return bytearray(s.to_bytes(n, "big"))


def _drop_opaque_alpha(rgba: bytearray) -> bytearray:
    """RGBA -> RGB, only if every pixel is fully opaque: otherwise what you see is not what is signed."""
    alpha = rgba[3::4]
    if alpha.count(255) != len(alpha):
        raise PngError("transparent pixels are not supported (every alpha must be 255)")
    rgb = bytearray(len(alpha) * 3)
    rgb[0::3] = rgba[0::4]
    rgb[1::3] = rgba[1::4]
    rgb[2::3] = rgba[2::4]
    return rgb


# ---------------------------------------------------------------- writing
def write_png(image: Image, sidecar: str | None = None) -> bytes:
    """Uncompressed PNG; with `sidecar`, the JSON goes into one zTXt chunk "velum.sidecar" before IDAT."""
    raw = b"".join(b"\x00" + image.row(y) for y in range(image.height))  # filter 0 on every row
    ihdr = struct.pack(">IIBBBBB", image.width, image.height, 8, COLOR_RGB, 0, 0, 0)
    text = b""
    if sidecar is not None:
        text = _chunk(b"zTXt", SIDECAR_KEYWORD + b"\x00\x00" + zlib.compress(sidecar.encode("ascii"), 9))
    return (SIGNATURE + _chunk(b"IHDR", ihdr) + text + _chunk(b"IDAT", _zlib_stored(raw))
            + _chunk(b"IEND", b""))


def _chunk(ctype: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + ctype + body + struct.pack(">I", zlib.crc32(ctype + body))


def _zlib_stored(data: bytes) -> bytes:
    """A zlib stream made only of uncompressed deflate blocks: header 78 01, blocks, Adler-32."""
    out = bytearray(b"\x78\x01")
    for start in range(0, len(data), _STORED_BLOCK_MAX):
        block = data[start:start + _STORED_BLOCK_MAX]
        final = 1 if start + _STORED_BLOCK_MAX >= len(data) else 0
        out += bytes([final]) + struct.pack("<HH", len(block), len(block) ^ 0xFFFF) + block
    out += struct.pack(">I", zlib.adler32(data))
    return bytes(out)
