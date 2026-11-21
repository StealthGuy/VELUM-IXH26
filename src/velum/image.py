"""An 8-bit RGB image in memory: the only pixel type VELUM works with (docs/VELUM.md section 3)."""
from __future__ import annotations

from dataclasses import dataclass

MAX_SIDE = 16384  # pixels per side
MAX_PIXELS = 1 << 25  # 33.5 MP (8K is 33.2 MP): bounds what a small file can make us inflate and process


def size_problem(width: int, height: int) -> str | None:
    """None if width x height is an acceptable image size, else why not."""
    if not (1 <= width <= MAX_SIDE and 1 <= height <= MAX_SIDE) or width * height > MAX_PIXELS:
        return f"image size {width}x{height} outside 1..{MAX_SIDE} per side or above {MAX_PIXELS} pixels"
    return None


@dataclass(frozen=True)
class Image:
    """`rgb` holds `width * height` pixels, row by row from the top, 3 bytes each (R, G, B)."""

    width: int
    height: int
    rgb: bytes

    def __post_init__(self) -> None:
        problem = size_problem(self.width, self.height)
        if problem:
            raise ValueError(problem)
        if len(self.rgb) != self.width * self.height * 3:
            raise ValueError("pixel buffer length does not match width * height * 3")

    def row(self, y: int) -> bytes:
        """The 3 * width bytes of pixel row y."""
        start = y * self.width * 3
        return self.rgb[start:start + self.width * 3]

    def pixel(self, x: int, y: int) -> tuple[int, int, int]:
        i = (y * self.width + x) * 3
        return self.rgb[i], self.rgb[i + 1], self.rgb[i + 2]
