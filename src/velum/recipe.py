"""Rendition: crop, rotate, downscale, brightness/contrast. Integers only (docs/VELUM.md section 6.4).

Order: crop -> rotate -> resize -> brightness/contrast. `//` is floor division everywhere.
"""
from __future__ import annotations

from .descriptor import Recipe
from .image import Image
from .tiles import TILE


def render(evidence: Image, crop: tuple[int, int, int, int] | None, recipe: Recipe | None) -> Image:
    img = crop_tiles(evidence, crop) if crop else evidence
    if recipe is None:
        return img
    img = rotate(img, recipe.rotate)
    if recipe.resize is not None:
        img = resize(img, *recipe.resize)
    return tone(img, recipe.brightness, recipe.contrast)


def output_size(width: int, height: int, crop: tuple[int, int, int, int] | None,
                recipe: Recipe | None) -> tuple[int, int]:
    """Size of the rendition; raises ValueError if the crop or the recipe cannot be applied."""
    w, h = width, height
    if crop:
        col0, row0, cols, rows = crop
        x0, y0 = col0 * TILE, row0 * TILE
        if col0 < 0 or row0 < 0 or cols < 1 or rows < 1 or x0 >= w or y0 >= h:
            raise ValueError("crop outside the image")
        w, h = min(cols * TILE, w - x0), min(rows * TILE, h - y0)
    if recipe:
        if recipe.rotate in (90, 270):
            w, h = h, w
        if recipe.resize:
            if not (recipe.resize[0] <= w and recipe.resize[1] <= h):
                raise ValueError(f"recipe resizes {w}x{h} to {recipe.resize[0]}x{recipe.resize[1]}: "
                                 "only shrinking is allowed")
            w, h = recipe.resize
    return w, h


def crop_tiles(img: Image, crop: tuple[int, int, int, int]) -> Image:
    """Crop to whole tiles; the last row/column may be shorter where the image ends."""
    w, h = output_size(img.width, img.height, crop, None)
    x0, y0 = crop[0] * TILE, crop[1] * TILE
    rgb = b"".join(img.rgb[((y0 + y) * img.width + x0) * 3:((y0 + y) * img.width + x0 + w) * 3] for y in range(h))
    return Image(w, h, rgb)


def rotate(img: Image, degrees: int) -> Image:
    """Clockwise. 90: out[r][c] = in[h-1-c][r]; 180: in[h-1-r][w-1-c]; 270: in[c][w-1-r]."""
    w, h = img.width, img.height
    if degrees not in (0, 90, 180, 270):
        raise ValueError("rotate must be 0, 90, 180 or 270")
    if degrees == 0:
        return img
    if degrees == 180:
        rows = [img.row(h - 1 - r) for r in range(h)]
        return Image(w, h, b"".join(_reverse_pixels(row) for row in rows))
    # 90 and 270: output row r is one input column (x = r read bottom-up for 90, x = w-1-r top-down for
    # 270). A column's channel is a strided slice of the buffer, so each row costs three C-level slices.
    out = bytearray(w * h * 3)
    src, stride, line = img.rgb, w * 3, h * 3
    for r in range(w):
        x = r if degrees == 90 else w - 1 - r
        step = -1 if degrees == 90 else 1
        for ch in range(3):
            out[r * line + ch:(r + 1) * line:3] = src[x * 3 + ch::stride][::step]
    return Image(h, w, bytes(out))


def _reverse_pixels(row: bytes) -> bytes:
    return b"".join(row[i:i + 3] for i in range(len(row) - 3, -1, -3))


def _area_weights(n_in: int, n_out: int) -> list[list[tuple[int, int]]]:
    """For each output index X, the (source index x, weight) pairs with
    weight = overlap of [x*n_out, (x+1)*n_out) and [X*n_in, (X+1)*n_in). Weights of one X sum to n_in."""
    table = []
    for big in range(n_out):
        lo, hi = big * n_in, (big + 1) * n_in
        pairs = []
        for x in range(lo // n_out, (hi - 1) // n_out + 1):
            overlap = min((x + 1) * n_out, hi) - max(x * n_out, lo)
            if overlap > 0:
                pairs.append((x, overlap))
        table.append(pairs)
    return table


def resize(img: Image, w_out: int, h_out: int) -> Image:
    """Exact area average, downscale only. Sums stay exact integers; one half-up rounding at the end:
    out = (sum of wy * wx * pixel + D // 2) // D with D = w_in * h_in."""
    w_in, h_in = img.width, img.height
    if not (1 <= w_out <= w_in and 1 <= h_out <= h_in):
        raise ValueError("resize can only shrink the image")
    wx, wy = _area_weights(w_in, w_out), _area_weights(h_in, h_out)
    # horizontal pass: rows of unrounded weighted sums, per channel
    horiz = []
    for y in range(h_in):
        row = img.row(y)
        line = []
        for pairs in wx:
            for ch in range(3):
                line.append(sum(weight * row[x * 3 + ch] for x, weight in pairs))
        horiz.append(line)
    # vertical pass and the single rounding
    d = w_in * h_in
    out = bytearray(w_out * h_out * 3)
    k = 0
    for pairs in wy:
        for j in range(w_out * 3):
            out[k] = (sum(weight * horiz[y][j] for y, weight in pairs) + d // 2) // d
            k += 1
    return Image(w_out, h_out, bytes(out))


def tone_table(brightness: int, contrast: int) -> bytes:
    """out = clamp(0, 255, ((in - 128) * (256 + contrast) + 128*256 + brightness*256 + 128) // 256)."""
    return bytes(max(0, min(255, ((v - 128) * (256 + contrast) + 128 * 256 + brightness * 256 + 128) // 256))
                 for v in range(256))


def tone(img: Image, brightness: int, contrast: int) -> Image:
    if brightness == 0 and contrast == 0:
        return img
    return Image(img.width, img.height, img.rgb.translate(tone_table(brightness, contrast)))
