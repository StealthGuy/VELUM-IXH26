"""Bitmap, descriptor, manifest, sidecar and trust-list formats, including strict-parsing rejections."""
from __future__ import annotations

import json
from collections.abc import Callable

import pytest

from scenario import AUTHORITY, LAB, build
from velum.canonical import CanonicalError
from velum.descriptor import Descriptor, Recipe, decode_bitmap, encode_bitmap
from velum.manifest import Manifest
from velum.schema import SchemaError
from velum.sidecar import Sidecar
from velum.trust import parse_trust_list

TX = "AB" * 32


def test_bitmap_is_msb_first() -> None:
    assert encode_bitmap(frozenset({0, 9}), 10) == "8040"  # the example in docs/VELUM.md 6.1
    assert decode_bitmap("8040", 10, "x") == frozenset({0, 9})
    with pytest.raises(SchemaError):
        decode_bitmap("8020", 10, "x")  # bit for tile 10 set, but n = 10
    with pytest.raises(SchemaError):
        decode_bitmap("80", 10, "x")  # wrong length


def test_descriptor_roundtrip_and_canonical_form() -> None:
    d = Descriptor(manifest_tx=TX, producer=LAB, n=12, hidden=frozenset({5}),
                   crop=(0, 0, 3, 2), recipe=Recipe(90, (50, 77), -10, 20))
    assert Descriptor.from_json(json.loads(d.canonical()), 12, "d") == d
    assert d.canonical().startswith(b'{"crop":[0,0,3,2],"hidden":"0400","manifest_tx":"ABAB')
    with pytest.raises(SchemaError):
        Recipe.from_json({"rotate": 45, "resize": None, "brightness": 0, "contrast": 0}, "r")


def test_descriptor_rejects_tiles_outside_the_grid() -> None:
    with pytest.raises(ValueError, match="outside"):
        Descriptor(manifest_tx=TX, producer=LAB, n=15, hidden=frozenset({16}))


def test_manifest_rejects_unexpected_values() -> None:
    good = Manifest(1280, 720, bytes(32), AUTHORITY).to_json()
    assert Manifest.from_json(good) == Manifest(1280, 720, bytes(32), AUTHORITY)
    for key, bad in (("tile", 32), ("pq_alg", "ML-DSA-65"), ("v", 2), ("authority", "rNotAnAddress")):
        with pytest.raises(SchemaError):
            Manifest.from_json({**good, key: bad})


def test_sidecar_roundtrip() -> None:
    world = build()
    for _, sc in world.levels:
        assert Sidecar.parse(sc.to_text()) == sc


@pytest.mark.parametrize("mutate, error", [
    (lambda t: t.replace('"velum": 1', '"velum": 1.0'), CanonicalError),  # a float in disguise
    (lambda t: t.replace('"velum": 1', '"velum": 1, "velum": 1'), CanonicalError),  # duplicate key
    (lambda t: t.replace('"velum": 1', '"velum": true'), CanonicalError),  # boolean
    (lambda t: t.replace('"velum": 1', '"velum": 1, "comment": "x"'), SchemaError),  # unknown key
])
def test_sidecar_strict_text_rules(mutate: Callable[[str], str], error: type[Exception]) -> None:
    text = build().levels[1][1].to_text()
    with pytest.raises(error):
        Sidecar.parse(mutate(text))


def test_sidecar_rejects_a_salt_for_a_hidden_tile_and_bad_tile_lists() -> None:
    value = json.loads(build().levels[1][1].to_text())  # L1: tile 5 hidden
    leak = json.loads(json.dumps(value))
    leak["visible"].insert(5, [5, "00" * 32])  # tile 5 now listed twice: with a salt and as hidden
    missing = json.loads(json.dumps(value))
    missing["visible"].pop(0)
    upper = json.loads(json.dumps(value))
    upper["visible"][0][1] = upper["visible"][0][1].upper()
    unsorted = json.loads(json.dumps(value))
    unsorted["visible"][0], unsorted["visible"][1] = unsorted["visible"][1], unsorted["visible"][0]
    for bad in (leak, missing, upper, unsorted):
        with pytest.raises(SchemaError):
            Sidecar.parse(json.dumps(bad))


def test_trust_list() -> None:
    entry = {"name": "Unit", "network": "testnet", "xrpl_address": AUTHORITY,
             "mldsa44_pk_sha256": "ab" * 32, "not_after": "2027-12-31T23:59:59Z"}
    (a,) = parse_trust_list(json.dumps([entry]))
    assert a.not_after == 1830297599 and a.accepts_time(1830297598) and not a.accepts_time(1830297599)
    with pytest.raises(SchemaError):
        parse_trust_list(json.dumps([{**entry, "not_after": "31/12/2027"}]))
    with pytest.raises(SchemaError):
        parse_trust_list(json.dumps([{**entry, "not_after": "2027-1-1T1:1:1Z"}]))  # strptime alone accepts it


def test_trust_list_refuses_duplicate_keys() -> None:
    """Two entries for one key would make revocation depend on their order."""
    entry = {"name": "Unit", "network": "testnet", "xrpl_address": AUTHORITY,
             "mldsa44_pk_sha256": "ab" * 32, "not_after": None}
    with pytest.raises(SchemaError, match="duplicate"):
        parse_trust_list(json.dumps([entry, {**entry, "not_after": "2027-12-31T23:59:59Z"}]))
    rotated = {**entry, "mldsa44_pk_sha256": "cd" * 32}  # key rotation: same address, new key
    mainnet = {**entry, "network": "mainnet"}  # same address and key on another network
    assert len(parse_trust_list(json.dumps([mainnet, entry, rotated]))) == 3
