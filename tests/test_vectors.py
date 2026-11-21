"""The conformance vectors in tests/vectors/core_v1.json still match the reference code."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from velum import merkle
from velum.canonical import canonical_bytes
from velum.png import PngError, SidecarError, read_png, read_sidecar
from velum.descriptor import Recipe, encode_bitmap
from velum.ledger import LedgerTx, LedgerUnavailable, TxNotFound
from velum.recipe import render
from velum.tiles import TILE_BYTES, derive_salt, grid_of, leaf_hash, tile_bytes
from velum.trust import parse_trust_list
from velum.verify import verify

VECTORS: dict[str, Any] = json.loads((Path(__file__).parent / "vectors" / "core_v1.json").read_text())


def test_png_decode_cases() -> None:
    for case in VECTORS["png_decode"]:
        img = read_png(base64.b64decode(case["png_b64"]))
        assert (img.width, img.height) == (case["width"], case["height"]), case["name"]
        assert hashlib.sha256(img.rgb).hexdigest() == case["rgb_sha256"], case["name"]


def test_png_reject_cases() -> None:
    for case in VECTORS["png_reject"]:
        with pytest.raises(PngError):
            read_png(base64.b64decode(case["png_b64"]))


def test_png_verify_reject_cases() -> None:
    for case in VECTORS["png_verify_reject"]:
        png = base64.b64decode(case["png_b64"])
        read_png(png)  # decodes...
        with pytest.raises(PngError):  # ...but a verifier refuses it
            read_png(png, strict=True)


def test_png_sidecar_cases() -> None:
    for case in VECTORS["png_sidecar"]:
        png = base64.b64decode(case["png_b64"])
        if case["sidecar"] == "ERROR":
            with pytest.raises(SidecarError):
                read_sidecar(png)
        else:
            assert read_sidecar(png) == case["sidecar"], case["name"]


def test_tree_vectors() -> None:
    tree = VECTORS["tree"]
    secret = bytes.fromhex(tree["K_hex"])
    leaves = [leaf_hash(i, derive_salt(secret, i), bytes(TILE_BYTES)) for i in range(3)]
    assert [derive_salt(secret, i).hex() for i in range(3)] == tree["salts"]
    assert [x.hex() for x in leaves] == tree["leaves"]
    assert {n: merkle.root(leaves[:int(n)]).hex() for n in tree["roots"]} == tree["roots"]


def test_image_case() -> None:
    case = VECTORS["image_case"]
    img = read_png(base64.b64decode(case["png_b64"]))
    secret = bytes.fromhex(case["K_hex"])
    g = grid_of(img)
    assert (g.cols, g.rows) == (case["cols"], case["rows"])
    assert [hashlib.sha256(tile_bytes(img, i)).hexdigest() for i in range(g.n)] == case["tile_sha256"]
    leaves = [leaf_hash(i, derive_salt(secret, i), tile_bytes(img, i)) for i in range(g.n)]
    assert [x.hex() for x in leaves] == case["leaves"]
    assert merkle.root(leaves).hex() == case["root"]


def test_canonical_json_cases() -> None:
    for case in VECTORS["canonical_json"]:
        assert canonical_bytes(case["value"]).decode("ascii") == case["canonical"]


# ---------------------------------------------------------------- levels_v1.json
LEVELS: dict[str, Any] = json.loads((Path(__file__).parent / "vectors" / "levels_v1.json").read_text())


class DumpLedger:
    """Replays the ledger dump shipped with the vectors."""

    network = "testnet"

    def __init__(self, dump: dict[str, Any], down: bool = False) -> None:
        self.down = down
        self.txs = {h: LedgerTx(hash=h, validated=t["validated"], result=t["result"], tx_type=t["tx_type"],
                                account=t["account"], memos=tuple((m[0], bytes.fromhex(m[1])) for m in t["memos"]),
                                ledger_index=t["ledger_index"], close_time=t["close_time"])
                    for h, t in dump.items()}

    def transaction(self, tx_hash: str) -> LedgerTx:
        if self.down:
            raise LedgerUnavailable("vector case: ledger down")
        if tx_hash not in self.txs:
            raise TxNotFound(tx_hash)
        return self.txs[tx_hash]


def test_level_cases() -> None:
    ledgers = {"dump": DumpLedger(LEVELS["ledger"]), "down": DumpLedger(LEVELS["ledger"], down=True)}
    trust = {name: parse_trust_list(json.dumps(entries)) for name, entries in LEVELS["trust_lists"].items()}
    for case in LEVELS["cases"]:
        files = LEVELS["png_files"]
        rendition = base64.b64decode(files[case["rendition_png"]]) if case["rendition_png"] else None
        report = verify(base64.b64decode(files[case["evidence_png"]]), case["sidecar"], trust[case["trust"]],
                        ledgers[case["ledger"]], rendition)
        assert report.status == case["expected_status"], (case["name"], report.lines())
        assert [c.id for c in report.checks if not c.ok and not c.inconclusive] == case["expected_failed"], case["name"]
        assert [c.id for c in report.checks if c.inconclusive] == case["expected_unknown"], case["name"]


def test_vector_files_match_the_reference_code() -> None:
    """The vectors are generated, never edited: regenerate with scripts/make_vectors.py."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("make_vectors", Path(__file__).parent.parent / "scripts" / "make_vectors.py")
    assert spec is not None and spec.loader is not None
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    assert gen.build() == VECTORS, "core_v1.json is stale: run scripts/make_vectors.py"
    assert gen.build_levels() == LEVELS, "levels_v1.json is stale: run scripts/make_vectors.py"


def test_recipe_cases() -> None:
    for case in LEVELS["recipe"]:
        crop = tuple(case["crop"]) if case["crop"] else None
        rec = Recipe.from_json(case["recipe"], "r") if case["recipe"] else None
        out = render(read_png(base64.b64decode(case["input_png_b64"])), crop, rec)
        assert out == read_png(base64.b64decode(case["output_png_b64"])), case["name"]


def test_bitmap_cases() -> None:
    for case in LEVELS["bitmap"]:
        assert encode_bitmap(frozenset(case["hidden"]), case["n"]) == case["hex"]
