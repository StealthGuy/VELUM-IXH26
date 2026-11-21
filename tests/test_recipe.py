"""Rendition recipe (docs/VELUM.md section 6.4), with hand-computed expectations."""
from __future__ import annotations

import pytest

from helpers import gradient
from velum.descriptor import Recipe
from velum.image import Image
from velum.recipe import crop_tiles, render, resize, rotate, tone, tone_table

IMG = Image(7, 5, gradient(7, 5))


def gray_row(values: list[int]) -> Image:
    return Image(len(values), 1, bytes(v for v in values for _ in range(3)))


def test_identity() -> None:
    assert render(IMG, None, None) == IMG
    assert render(IMG, None, Recipe()) == IMG


def test_rotations() -> None:
    a = Image(2, 1, bytes([1, 1, 1, 2, 2, 2]))  # pixels: A B
    assert rotate(a, 90) == Image(1, 2, bytes([1, 1, 1, 2, 2, 2]))  # clockwise: A on top, B below
    assert rotate(a, 270) == Image(1, 2, bytes([2, 2, 2, 1, 1, 1]))
    assert rotate(a, 180) == Image(2, 1, bytes([2, 2, 2, 1, 1, 1]))
    assert rotate(rotate(IMG, 90), 270) == IMG
    assert rotate(rotate(rotate(rotate(IMG, 90), 90), 90), 90) == IMG
    assert rotate(rotate(IMG, 180), 180) == IMG
    with pytest.raises(ValueError):
        rotate(IMG, 45)


def test_resize_exact_area_weights() -> None:
    # 3 -> 2: out0 = (2*0 + 1*30) / 3 = 10, out1 = (1*30 + 2*60) / 3 = 50
    assert resize(gray_row([0, 30, 60]), 2, 1) == gray_row([10, 50])
    # half-up rounding at the end: (1 + 2) / 2 = 1.5 -> 2;  (1 + 1 + 1 + 2) / 4 = 1.25 -> 1
    assert resize(gray_row([1, 2]), 1, 1) == gray_row([2])
    assert resize(Image(2, 2, bytes([1] * 9 + [2] * 3)), 1, 1) == gray_row([1])
    assert resize(IMG, 7, 5) == IMG  # same size: identity
    with pytest.raises(ValueError):
        resize(IMG, 8, 5)  # never upscale


def test_tone() -> None:
    assert tone_table(0, 0) == bytes(range(256))
    t = tone_table(0, 255)
    assert (t[127], t[128], t[129]) == (126, 128, 130)  # (+-1 * 511 + 32896) // 256
    assert tone_table(255, 0)[1] == 255 and tone_table(-255, 0)[254] == 0  # clamped
    assert tone(IMG, 10, 0).rgb == bytes(min(255, v + 10) for v in IMG.rgb)


def test_crop_tiles_keeps_whole_tiles_and_clips_at_the_edge() -> None:
    img = Image(200, 130, gradient(200, 130))
    inner = crop_tiles(img, (1, 1, 1, 1))
    assert (inner.width, inner.height) == (64, 64) and inner.pixel(0, 0) == img.pixel(64, 64)
    corner = crop_tiles(img, (3, 2, 1, 1))  # bottom-right edge tile: 8 x 2 real pixels
    assert (corner.width, corner.height) == (8, 2) and corner.pixel(7, 1) == img.pixel(199, 129)
