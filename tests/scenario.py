"""TEST ONLY: the reference copies AUTHORITY -> LAB -> NEWSROOM on a 200 x 130 synthetic image.

Grid 4 x 3 = 12 tiles; the right column (8 px) and bottom row (2 px) are edge tiles, so padding is
always exercised. Everything is deterministic (fixed keys, deterministic signature, MemLedger).

    L0  authority, from the original, nothing hidden
    L1  LAB, from L0, hides tile 5
    L2  NEWSROOM, from L1, hides tile 6 too, crops to tiles (0,0)-(2,1) (which hides 3, 7, 8, 9, 10, 11),
        rotates 90, shrinks to 50 x 77, brightness +10, contrast +20
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from xrpl import CryptoAlgorithm
from xrpl.core.keypairs import derive_classic_address, derive_keypair, generate_seed

from helpers import gradient
from memledger import MemLedger
from velum import manifest as mf
from velum import pq
from velum.descriptor import MEMO_TYPE as LEVEL_MEMO
from velum.descriptor import Recipe
from velum.image import Image
from velum.level import commit, from_level, from_master, release_level, release_master
from velum.recipe import render
from velum.sidecar import Sidecar
from velum.trust import Authority

K = bytes(range(32))
AUTHORITY_SEED = bytes([7]) * 32


def address(n: int) -> str:
    seed = generate_seed(f"{n:032x}", CryptoAlgorithm.ED25519)
    return derive_classic_address(derive_keypair(seed)[0])


AUTHORITY, LAB, NEWSROOM, STRANGER = address(1), address(2), address(3), address(4)


@dataclass
class World:
    ledger: MemLedger
    original: Image
    pk: bytes
    sk: bytes
    trust: list[Authority]
    levels: list[tuple[Image, Sidecar]]  # (evidence, sidecar) for L0, L1, L2
    rendition: Image  # of L2


def build() -> World:
    led = MemLedger()
    original = Image(200, 130, gradient(200, 130))
    pk, sk = pq.keypair(AUTHORITY_SEED)

    manifest = mf.Manifest(original.width, original.height, commit(original, K), AUTHORITY)
    sig = mf.sign(manifest, sk, deterministic=True)
    manifest_tx = led.anchor(AUTHORITY, mf.MEMO_TYPE, mf.memo_data(manifest, sig))

    d0 = from_master(manifest, manifest_tx)
    l0 = release_master(original, K, manifest, sig, pk, manifest_tx, d0,
                        led.anchor(AUTHORITY, LEVEL_MEMO, d0.memo_data()))

    d1 = from_level(l0[1], LAB, hide=frozenset({5}))
    l1 = release_level(l0[0], l0[1], d1, led.anchor(LAB, LEVEL_MEMO, d1.memo_data()))

    d2 = from_level(l1[1], NEWSROOM, hide=frozenset({6}), crop=(0, 0, 3, 2),
                    recipe=Recipe(rotate=90, resize=(50, 77), brightness=10, contrast=20))
    l2 = release_level(l1[0], l1[1], d2, led.anchor(NEWSROOM, LEVEL_MEMO, d2.memo_data()))

    trust = [Authority("Test Authority", "testnet", AUTHORITY, hashlib.sha256(pk).digest(), None)]
    return World(led, original, pk, sk, trust, [l0, l1, l2], render(l2[0], d2.crop, d2.recipe))
