"""Tile grid, padding, salts, leaves and the RFC 6962 root, against the vectors in docs/VELUM.md section 4."""
from __future__ import annotations

import hashlib

import pytest

from helpers import gradient
from velum import merkle
from velum.image import Image
from velum.tiles import TILE_BYTES, Grid, derive_salt, leaf_hash, tile_bytes

K = bytes(range(32))
ZERO_TILE = bytes(TILE_BYTES)
DOC_SALTS = [
    "d760c2b4790d8555c845941f0a37046f92b78ee35ef0dab13e749bb843a0573c",
    "9e195931165f4b0f08aa359f48f48d1a1b283f9d739a2a27fd7dd421bcf61165",
    "9d98a6bfad1c1f6480b535ed2296fff2acde65c5e43af5736e54d6cdd9315f87",
]
DOC_LEAVES = [
    "3978b5fa612f7d0d0073d57b4a6b463ea1bb9fd38174bd188274c54cae30fabc",
    "685976bfcc3aec539e5def6995b36f4dc275de24ab05b896dc2479395d9a8354",
    "4b91a7878c424b0cf5905647103c3b7811ce305af90036cfb07726cf7efafd7b",
]
DOC_ROOTS = {
    1: "3978b5fa612f7d0d0073d57b4a6b463ea1bb9fd38174bd188274c54cae30fabc",
    2: "c9a0d01fd7d235261c8e223cb106f86843b9713a7f0c36b75ef294ab6af06de1",
    3: "9fd03a9407f4c01d5e024a957d979b7227b913511622313e7ad73fa41b4266ca",
}


def test_grid_for_720p() -> None:
    g = Grid(1280, 720)
    assert (g.cols, g.rows, g.n) == (20, 12, 240)
    assert g.rect(0) == (0, 0, 64, 64)
    assert g.rect(239) == (1216, 704, 64, 16)  # last row: only 16 real pixel rows
    with pytest.raises(IndexError):
        g.rect(240)


def test_edge_tile_is_zero_padded() -> None:
    img = Image(70, 66, gradient(70, 66))  # grid 2 x 2, right and bottom tiles are partial
    t = tile_bytes(img, 3)  # bottom-right: 6 x 2 real pixels
    assert len(t) == TILE_BYTES
    assert t[:6 * 3] == img.rgb[(64 * 70 + 64) * 3:(64 * 70 + 70) * 3]  # first real row
    assert t[6 * 3:64 * 3] == bytes(58 * 3)  # right padding of that row
    assert t[2 * 64 * 3:] == bytes(62 * 64 * 3)  # 62 padding rows


def test_doc_vectors_for_salts_and_leaves() -> None:
    for i in range(3):
        assert derive_salt(K, i).hex() == DOC_SALTS[i]
        assert leaf_hash(i, derive_salt(K, i), ZERO_TILE).hex() == DOC_LEAVES[i]


def test_doc_vectors_for_roots() -> None:
    leaves = [bytes.fromhex(h) for h in DOC_LEAVES]
    for n, expected in DOC_ROOTS.items():
        assert merkle.root(leaves[:n]).hex() == expected


def test_root_follows_rfc6962_split_for_five_leaves() -> None:
    leaves = [hashlib.sha256(bytes([i])).digest() for i in range(5)]

    def node(a: bytes, b: bytes) -> bytes:
        return hashlib.sha256(b"\x01" + a + b).digest()

    left = node(node(leaves[0], leaves[1]), node(leaves[2], leaves[3]))  # k = 4
    assert merkle.root(leaves) == node(left, leaves[4])


def test_leaf_binds_index_salt_and_content() -> None:
    salt = derive_salt(K, 0)
    base = leaf_hash(0, salt, ZERO_TILE)
    assert leaf_hash(1, salt, ZERO_TILE) != base  # same tile moved elsewhere
    assert leaf_hash(0, derive_salt(K, 1), ZERO_TILE) != base  # another salt
    assert leaf_hash(0, salt, b"\x01" + ZERO_TILE[1:]) != base  # one byte changed


def test_bad_inputs_are_rejected() -> None:
    with pytest.raises(ValueError):
        derive_salt(b"short", 0)
    with pytest.raises(ValueError):
        leaf_hash(0, b"x" * 31, ZERO_TILE)
    with pytest.raises(ValueError):
        merkle.root([])
    with pytest.raises(ValueError):
        merkle.root([b"x" * 31])
