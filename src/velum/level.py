"""Making redacted copies, called levels (docs/VELUM.md section 6). Pure functions: anchoring happens
elsewhere.

Authority:  root = commit(image, K) -> Manifest -> sign -> anchor (manifest_tx)
            d = from_master(manifest, manifest_tx, ...) -> anchor (tx) -> evidence, sidecar = release_master(...)
Anyone:     d = from_level(sidecar, producer, ...) -> anchor (tx) -> evidence, sidecar = release_level(...)
            rendition = recipe.render(evidence, d.crop, d.recipe)

A level made from another level always hides at least what its source hides: without the salts of the
hidden tiles there is no way to show them again, so black can only be added.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from . import merkle
from .descriptor import Descriptor, Recipe
from .image import Image
from .manifest import Manifest
from .recipe import output_size
from .sidecar import Sidecar
from .tiles import Grid, all_leaves, derive_salt, grid_of, leaf_hash, tile_bytes

Crop = tuple[int, int, int, int]  # col0, row0, cols, rows (tile units)


@dataclass(frozen=True)
class Disclosure:
    """What a level holder knows: salts of the visible tiles, leaf hashes of the hidden ones."""

    visible: dict[int, bytes]
    hidden: dict[int, bytes]


def commit(image: Image, secret: bytes) -> bytes:
    """The Merkle root the authority signs."""
    return merkle.root(all_leaves(image, secret))


def outside_crop(grid: Grid, crop: Crop | None) -> frozenset[int]:
    """Tiles outside the crop rectangle (empty if no crop). Raises if the crop leaves the grid."""
    if crop is None:
        return frozenset()
    col0, row0, cols, rows = crop
    if not (0 <= col0 < col0 + cols <= grid.cols and 0 <= row0 < row0 + rows <= grid.rows):
        raise ValueError(f"crop {crop} outside the {grid.cols}x{grid.rows} tile grid")
    return frozenset(i for i in range(grid.n)
                     if not (col0 <= i % grid.cols < col0 + cols and row0 <= i // grid.cols < row0 + rows))


def _descriptor(manifest: Manifest, manifest_tx: str, producer: str, already_hidden: frozenset[int],
                hide: frozenset[int], crop: Crop | None, recipe: Recipe | None) -> Descriptor:
    grid = Grid(manifest.width, manifest.height)
    output_size(grid.width, grid.height, crop, recipe)  # raises now, before anything is anchored (V5 would fail)
    return Descriptor(manifest_tx=manifest_tx, producer=producer, n=grid.n,
                      hidden=already_hidden | hide | outside_crop(grid, crop), crop=crop, recipe=recipe)


def from_master(manifest: Manifest, manifest_tx: str, hide: frozenset[int] = frozenset(),
                crop: Crop | None = None, recipe: Recipe | None = None) -> Descriptor:
    """Authority: describe a copy made from the original. The authority is the producer."""
    return _descriptor(manifest, manifest_tx, manifest.authority, frozenset(), hide, crop, recipe)


def from_level(source: Sidecar, producer: str, hide: frozenset[int] = frozenset(),
               crop: Crop | None = None, recipe: Recipe | None = None) -> Descriptor:
    """Anyone holding a level: describe a more redacted copy (source's hidden tiles + `hide` + outside crop)."""
    return _descriptor(source.manifest, source.manifest_tx, producer, source.level.hidden, hide, crop, recipe)


def redact(image: Image, known: Disclosure, hide: frozenset[int]) -> tuple[Image, Disclosure]:
    """Hide more tiles: replace each newly hidden tile's salt by its leaf hash and paint it black."""
    visible, hidden = dict(known.visible), dict(known.hidden)
    unknown = hide - set(visible) - set(hidden)
    if unknown:
        raise ValueError(f"tiles {sorted(unknown)} are not in this level")
    rgb = bytearray(image.rgb)
    grid = grid_of(image)
    for i in sorted(hide - set(hidden)):
        hidden[i] = leaf_hash(i, visible.pop(i), tile_bytes(image, i))  # the salt is dropped here
        x0, y0, w, h = grid.rect(i)
        for y in range(y0, y0 + h):
            start = (y * image.width + x0) * 3
            rgb[start:start + w * 3] = bytes(w * 3)
    return Image(image.width, image.height, bytes(rgb)), Disclosure(visible, hidden)


def release_master(original: Image, secret: bytes, manifest: Manifest, manifest_sig: bytes, authority_pk: bytes,
                   manifest_tx: str, descriptor: Descriptor, tx: str) -> tuple[Image, Sidecar]:
    """Authority: evidence image and sidecar of a copy made from the original, anchored in `tx`."""
    master = Disclosure({i: derive_salt(secret, i) for i in range(grid_of(original).n)}, {})
    evidence, known = redact(original, master, descriptor.hidden)
    return evidence, Sidecar(manifest=manifest, manifest_sig=manifest_sig, authority_pk=authority_pk,
                             manifest_tx=manifest_tx, level=descriptor, level_tx=tx,
                             visible=known.visible, hidden=known.hidden)


def release_level(source_evidence: Image, source: Sidecar, descriptor: Descriptor, tx: str) -> tuple[Image, Sidecar]:
    """Anyone: evidence image and sidecar of a more redacted copy of `source`, anchored in `tx`."""
    evidence, known = redact(source_evidence, Disclosure(source.visible, source.hidden), descriptor.hidden)
    return evidence, replace(source, level=descriptor, level_tx=tx, visible=known.visible, hidden=known.hidden)
