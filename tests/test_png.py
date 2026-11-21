"""PNG reader and writer (docs/VELUM.md section 3)."""
from __future__ import annotations

import struct
import zlib

import pytest

from helpers import SIGNATURE, chunk, encode_png, gradient
from velum.image import Image
from velum.png import PngError, SidecarError, read_png, read_sidecar, write_png


@pytest.mark.parametrize("size", [(1, 1), (5, 3), (64, 64), (70, 33)])
def test_writer_roundtrip(size: tuple[int, int]) -> None:
    w, h = size
    img = Image(w, h, gradient(w, h))
    assert read_png(write_png(img)) == img


def test_writer_output_is_uncompressed_and_unfiltered() -> None:
    img = Image(300, 250, gradient(300, 250))  # > 65 535 bytes of data: several stored blocks
    data = write_png(img)
    assert data.startswith(SIGNATURE)
    assert data[12:16] == b"IHDR" and data[16 + 9] == 2  # colour type RGB
    idat_len = struct.unpack(">I", data[33:37])[0]
    stream = data[41:41 + idat_len]
    assert stream[:2] == b"\x78\x01"
    raw = zlib.decompress(stream)
    assert all(raw[y * (1 + 300 * 3)] == 0 for y in range(250))  # filter 0 on every row
    assert len(data) > len(raw)  # stored, not compressed


@pytest.mark.parametrize("filters", [(0,), (1,), (2,), (3,), (4,), (4, 3, 2, 1, 0)])
def test_reader_undoes_every_filter(filters: tuple[int, ...]) -> None:
    w, h = 37, 11
    pixels = gradient(w, h)
    assert read_png(encode_png(w, h, pixels, filters=filters)) == Image(w, h, pixels)


def test_reader_accepts_opaque_rgba_and_ignores_ancillary_chunks() -> None:
    w, h = 9, 4
    rgb = gradient(w, h)
    rgba = b"".join(rgb[i:i + 3] + b"\xff" for i in range(0, len(rgb), 3))
    extras = [chunk(b"gAMA", struct.pack(">I", 45455)), chunk(b"tEXt", b"Comment\x00hi")]
    assert read_png(encode_png(w, h, rgba, color_type=6, extra_chunks=extras)) == Image(w, h, rgb)


def test_reader_rejects_transparency() -> None:
    rgba = bytes([10, 20, 30, 255, 10, 20, 30, 254])
    with pytest.raises(PngError, match="alpha"):
        read_png(encode_png(2, 1, rgba, color_type=6))


@pytest.mark.parametrize("depth, color_type, interlace, message", [
    (16, 2, 0, "bit depth"),
    (8, 3, 0, "colour type"),
    (8, 2, 1, "interlaced"),
])
def test_reader_rejects_unsupported_formats(depth: int, color_type: int, interlace: int, message: str) -> None:
    png = encode_png(2, 2, bytes(12), color_type=color_type, depth=depth, interlace=interlace)
    with pytest.raises(PngError, match=message):
        read_png(png)


def test_reader_rejects_corruption() -> None:
    good = encode_png(4, 4, gradient(4, 4))
    with pytest.raises(PngError, match="signature"):
        read_png(b"\x00" + good[1:])
    flipped = bytearray(good)
    flipped[40] ^= 1  # inside IHDR/IDAT: CRC no longer matches
    with pytest.raises(PngError, match="CRC"):
        read_png(bytes(flipped))
    with pytest.raises(PngError, match="truncated"):
        read_png(good[:-5])
    with pytest.raises(PngError, match="after IEND"):
        read_png(good + b"x")
    with pytest.raises(PngError, match="critical"):
        read_png(encode_png(4, 4, gradient(4, 4), extra_chunks=[chunk(b"ABCD", b"")]))


def test_reader_refuses_more_data_than_the_header_allows() -> None:
    """A tiny header with a huge stream must fail without inflating it (zip bomb guard)."""
    raw = b"\x00" + bytes(3) + bytes(10_000_000)
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    bomb = SIGNATURE + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    with pytest.raises(PngError, match="wrong size"):
        read_png(bomb)


def test_reader_refuses_huge_dimensions_before_inflating() -> None:
    """A small file declaring 16384 x 16384 (1 GiB of RGBA once inflated) is refused at the header."""
    ihdr = struct.pack(">IIBBBBB", 16384, 16384, 8, 6, 0, 0, 0)
    png = SIGNATURE + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"\x00" * 1000)) + chunk(b"IEND", b"")
    with pytest.raises(PngError, match="pixels"):
        read_png(png)


def test_reader_requires_consecutive_idat_chunks() -> None:
    good = encode_png(4, 4, gradient(4, 4))  # IHDR, IDAT, IDAT, IEND
    ihdr_end = 8 + 25
    first_len = struct.unpack(">I", good[ihdr_end:ihdr_end + 4])[0]
    split = ihdr_end + 12 + first_len  # after the first IDAT
    broken = good[:split] + chunk(b"tEXt", b"k\x00v") + good[split:]
    with pytest.raises(PngError, match="consecutive"):
        read_png(broken)


# ---------------------------------------------------------------- embedded sidecar (zTXt "velum.sidecar")
def test_sidecar_roundtrip_does_not_touch_pixels() -> None:
    img = Image(9, 7, gradient(9, 7))
    with_text = write_png(img, '{"velum":1}')
    assert read_png(with_text) == img
    assert read_sidecar(with_text) == '{"velum":1}'
    assert read_sidecar(write_png(img)) is None


def test_sidecar_chunk_rules() -> None:
    def ztxt(keyword: bytes, payload: bytes, method: int = 0) -> bytes:
        return chunk(b"zTXt", keyword + b"\x00" + bytes([method]) + payload)

    def png_with(*chunks: bytes) -> bytes:
        good = encode_png(2, 2, bytes(12))
        return good[:33] + b"".join(chunks) + good[33:]  # right after IHDR

    one = ztxt(b"velum.sidecar", zlib.compress(b"{}"))
    assert read_sidecar(png_with(ztxt(b"Comment", zlib.compress(b"hi")))) is None  # other keywords ignored
    with pytest.raises(PngError, match="more than one"):
        read_sidecar(png_with(one, one))
    with pytest.raises(PngError, match="too large"):
        read_sidecar(png_with(ztxt(b"velum.sidecar", zlib.compress(b" " * (5 << 20)))))  # bomb guard
    with pytest.raises(PngError, match="not ASCII"):
        read_sidecar(png_with(ztxt(b"velum.sidecar", zlib.compress("café".encode()))))
    with pytest.raises(PngError, match="compression"):
        read_sidecar(png_with(ztxt(b"velum.sidecar", b"", method=1)))


# ---------------------------------------------------------------- audit fixes
@pytest.mark.parametrize("ctype", [b"acTL", b"fcTL", b"fdAT", b"tRNS", b"gAMA", b"cHRM", b"iCCP", b"sRGB", b"sBIT",
                                   b"eXIf", b"pHYs", b"zzZz"])
def test_strict_reader_refuses_chunks_that_change_the_display(ctype: bytes) -> None:
    png = encode_png(4, 4, gradient(4, 4), extra_chunks=[chunk(ctype, b"\x00" * 8)])
    assert read_png(png) == Image(4, 4, gradient(4, 4))  # still decodable (signing an original is lenient)
    with pytest.raises(PngError, match="not allowed"):
        read_png(png, strict=True)


def test_strict_reader_allows_text_and_time() -> None:
    extras = [chunk(b"tEXt", b"k\x00v"), chunk(b"iTXt", b"k\x00\x00\x00\x00\x00v"), chunk(b"tIME", bytes(7))]
    png = encode_png(4, 4, gradient(4, 4), extra_chunks=extras)
    assert read_png(png, strict=True) == Image(4, 4, gradient(4, 4))
    assert read_png(write_png(Image(4, 4, gradient(4, 4)), "{}"), strict=True)  # the sidecar zTXt is fine


def test_pixel_budget_is_checked_before_inflating() -> None:
    png = encode_png(64, 64, bytes(64 * 64 * 3), filters=(4,))
    assert read_png(png, max_pixels=64 * 64).width == 64
    with pytest.raises(PngError, match="budget"):
        read_png(png, max_pixels=64 * 64 - 1)


def test_sidecar_chunk_errors_are_sidecar_errors() -> None:
    img = Image(3, 2, gradient(3, 2))
    one = write_png(img, '{"a":1}')
    ztxt = one[33:one.index(b"IDAT") - 4]
    two = one[:33] + ztxt + one[33:]
    with pytest.raises(SidecarError, match="more than one"):
        read_sidecar(two)
    with pytest.raises(PngError) as exc:
        read_sidecar(b"not a png")
    assert not isinstance(exc.value, SidecarError)  # an unreadable file is a different case


def test_duplicate_sidecar_rejected_before_second_inflate() -> None:
    img = Image(1, 1, bytes(3))
    png = write_png(img, "")
    # A corrupt second stream must be identified as a duplicate before decompression.
    duplicate = chunk(b"zTXt", b"velum.sidecar\0\0invalid")
    pos = png.index(b"IDAT") - 4
    with pytest.raises(SidecarError, match="more than one"):
        read_sidecar(png[:pos] + duplicate + png[pos:])
