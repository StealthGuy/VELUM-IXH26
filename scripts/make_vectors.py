"""Write tests/vectors/core_v1.json and levels_v1.json: conformance vectors for velum-js.

    .venv/bin/python scripts/make_vectors.py

Every value comes from the reference code. tests/test_vectors.py checks that the file still matches
the code, so the vectors cannot silently drift. Binary data is base64; hashes are lowercase hex.
"""
from __future__ import annotations

import base64
import hashlib
import json
import struct
import sys
import zlib
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from helpers import SIGNATURE, chunk, encode_png, gradient  # noqa: E402
from scenario import LAB, STRANGER  # noqa: E402  (test-only reference copies)
from scenario import build as build_world  # noqa: E402

from velum import merkle  # noqa: E402
from velum.canonical import canonical_bytes  # noqa: E402
from velum.descriptor import MEMO_TYPE as LEVEL_MEMO  # noqa: E402
from velum.descriptor import Descriptor, Recipe, encode_bitmap  # noqa: E402
from velum.image import Image  # noqa: E402
from velum.level import release_level  # noqa: E402
from velum.png import write_png  # noqa: E402
from velum.recipe import render  # noqa: E402
from velum.tiles import TILE_BYTES, derive_salt, grid_of, leaf_hash, tile_bytes  # noqa: E402

OUT = ROOT / "tests" / "vectors" / "core_v1.json"
K = bytes(range(32))


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def png_decode_cases() -> list[dict[str, object]]:
    w, h = 13, 7
    rgb = gradient(w, h)
    rgba = b"".join(rgb[i:i + 3] + b"\xff" for i in range(0, len(rgb), 3))
    gama = [chunk(b"gAMA", struct.pack(">I", 45455))]
    pngs = {
        "velum-writer-uncompressed": write_png(Image(w, h, rgb)),
        "filter-1-sub": encode_png(w, h, rgb, filters=(1,)),
        "filter-2-up": encode_png(w, h, rgb, filters=(2,)),
        "filter-3-average": encode_png(w, h, rgb, filters=(3,)),
        "filter-4-paeth": encode_png(w, h, rgb, filters=(4,)),
        "filters-mixed-compressed": encode_png(w, h, rgb),
        "rgba-opaque-with-gama": encode_png(w, h, rgba, color_type=6, extra_chunks=gama),
    }
    return [{"name": k, "png_b64": b64(v), "width": w, "height": h, "rgb_sha256": sha(rgb)} for k, v in pngs.items()]


def png_reject_cases() -> list[dict[str, object]]:
    good = encode_png(4, 4, gradient(4, 4))
    bad_crc = bytearray(good)
    bad_crc[40] ^= 1
    split = 33 + 12 + struct.unpack(">I", good[33:37])[0]  # after the first of the two IDAT chunks
    pngs = {
        "transparent-pixel": encode_png(2, 1, bytes([1, 2, 3, 255, 1, 2, 3, 0]), color_type=6),
        "bit-depth-16": encode_png(2, 2, bytes(12), depth=16),
        "palette": encode_png(2, 2, bytes(12), color_type=3),
        "interlaced": encode_png(2, 2, bytes(12), interlace=1),
        "bad-crc": bytes(bad_crc),
        "data-after-iend": good + b"x",
        "truncated": good[:-5],
        "idat-not-consecutive": good[:split] + chunk(b"tEXt", b"k\x00v") + good[split:],
        "too-many-pixels": SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", 16384, 16384, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00" * 1000)) + chunk(b"IEND", b""),
    }
    return [{"name": k, "png_b64": b64(v)} for k, v in pngs.items()]


def png_verify_reject_cases() -> list[dict[str, object]]:
    """PNGs that decode (read_png) but that a verifier must refuse: these chunks can make a viewer show
    other pixels than the verified ones (docs/VELUM.md section 3)."""
    w, h = 4, 4
    rgb = gradient(w, h)
    chunks = {
        "apng-actl": chunk(b"acTL", struct.pack(">II", 2, 0)),
        "trns-black-transparent": chunk(b"tRNS", bytes(6)),
        "gama": chunk(b"gAMA", struct.pack(">I", 45455)),
        "srgb": chunk(b"sRGB", b"\x00"),
        "iccp": chunk(b"iCCP", b"p\x00\x00" + zlib.compress(b"not a real profile")),
        "exif": chunk(b"eXIf", b"MM\x00*\x00\x00\x00\x08\x00\x00"),
        "plte-suggestion": chunk(b"PLTE", bytes(3)),
    }
    return [{"name": k, "png_b64": b64(encode_png(w, h, rgb, extra_chunks=[v]))} for k, v in chunks.items()]


def png_sidecar_cases() -> list[dict[str, object]]:
    """PNGs that may carry a zTXt "velum.sidecar": expected text, or null when there is none."""
    img = Image(5, 3, gradient(5, 3))
    text = '{"example":"any sidecar text","velum":1}'
    with_text = write_png(img, text)
    ztxt = with_text[33:with_text.index(b"IDAT") - 4]
    return [{"name": "with-sidecar", "png_b64": b64(with_text), "sidecar": text},
            {"name": "without-sidecar", "png_b64": b64(write_png(img)), "sidecar": None},
            {"name": "two-sidecars-is-an-error", "png_b64": b64(with_text[:33] + ztxt + with_text[33:]),
             "sidecar": "ERROR"}]


def tree_vectors() -> dict[str, object]:
    zero = bytes(TILE_BYTES)
    salts = [derive_salt(K, i) for i in range(3)]
    leaves = [leaf_hash(i, salts[i], zero) for i in range(3)]
    return {
        "K_hex": K.hex(), "tile": "64*64*3 zero bytes",
        "salts": [s.hex() for s in salts], "leaves": [x.hex() for x in leaves],
        "roots": {str(n): merkle.root(leaves[:n]).hex() for n in (1, 2, 3)},
    }


def image_case() -> dict[str, object]:
    """A 70 x 66 image: 2 x 2 tiles, three of them partial, so padding is exercised."""
    img = Image(70, 66, gradient(70, 66))
    n = grid_of(img).n
    leaves = [leaf_hash(i, derive_salt(K, i), tile_bytes(img, i)) for i in range(n)]
    return {
        "png_b64": b64(write_png(img)), "width": 70, "height": 66, "K_hex": K.hex(),
        "cols": 2, "rows": 2, "tile_sha256": [sha(tile_bytes(img, i)) for i in range(n)],
        "leaves": [x.hex() for x in leaves], "root": merkle.root(leaves).hex(),
    }


def canonical_cases() -> list[dict[str, object]]:
    values: list[object] = [
        {"w": 1280, "h": 720, "v": 1, "tile": 64, "root": "ab", "pq_alg": "ML-DSA-44", "authority": "rXYZ"},
        {"crop": None, "recipe": {"rotate": 90, "resize": [640, 360], "brightness": -12, "contrast": 30}},
        {"z": [], "a": {}, "m": [1, [2, [3]]]},
    ]
    return [{"value": v, "canonical": canonical_bytes(v).decode("ascii")} for v in values]


def build() -> dict[str, object]:
    return {
        "version": 1,
        "about": "VELUM conformance vectors, see docs/VELUM.md. Generated by scripts/make_vectors.py.",
        "png_decode": png_decode_cases(),
        "png_reject": png_reject_cases(),
        "png_verify_reject": png_verify_reject_cases(),
        "png_sidecar": png_sidecar_cases(),
        "tree": tree_vectors(),
        "image_case": image_case(),
        "canonical_json": canonical_cases(),
    }


# ---------------------------------------------------------------- levels_v1.json
LEVELS_OUT = ROOT / "tests" / "vectors" / "levels_v1.json"


def _variant(ev: Image, mutate_offset: int, value: int | None = None) -> bytes:
    rgb = bytearray(ev.rgb)
    rgb[mutate_offset] = rgb[mutate_offset] ^ 1 if value is None else value
    return write_png(Image(ev.width, ev.height, bytes(rgb)))


def _with_chunk(png: bytes, extra: bytes) -> bytes:
    return png[:33] + extra + png[33:]  # right after IHDR


def _sidecar_chunk(png: bytes) -> bytes:
    return png[33:png.index(b"IDAT") - 4]  # the zTXt written by write_png right after IHDR


def build_levels() -> dict[str, object]:
    world = build_world()
    (ev0, sc0), (ev1, sc1), (ev2, sc2) = world.levels

    # an extra, maliciously anchored level must be in the ledger dump before we export it
    d_bad = Descriptor(sc0.manifest_tx, LAB, 12, frozenset({1}))
    ev_bad, sc_bad = release_level(ev0, sc0, d_bad, world.ledger.anchor(STRANGER, LEVEL_MEMO, d_bad.memo_data()))

    a = world.trust[0]
    entry = {"name": a.name, "network": a.network, "xrpl_address": a.xrpl_address,
             "mldsa44_pk_sha256": a.pk_sha256.hex(), "not_after": None}
    trust_lists = {"default": [entry], "empty": [], "revoked": [{**entry, "not_after": "2027-01-15T08:00:00Z"}],
                   "mainnet-listed-first": [{**entry, "network": "mainnet"}, entry]}

    files: dict[str, str] = {}  # every PNG once, keyed by its SHA-256

    def ref(png: bytes) -> str:
        files[sha(png)] = b64(png)
        return sha(png)

    def case(name: str, evidence: bytes, sidecar: str | None, rendition: bytes | None, trust: str,
             status: str, failed: list[str], unknown: tuple[str, ...] = (), ledger: str = "dump") -> dict[str, object]:
        """`failed`: checks that fail conclusively; `unknown`: inconclusive ones; ledger "down": every
        lookup raises LedgerUnavailable."""
        return {"name": name, "evidence_png": ref(evidence), "sidecar": sidecar,
                "rendition_png": ref(rendition) if rendition else None, "trust": trust, "ledger": ledger,
                "expected_status": status, "expected_failed": failed, "expected_unknown": list(unknown)}

    def edited(text: str, *path: str, value: object) -> str:
        """The sidecar text with one field replaced (no re-anchoring: the edit is the attack)."""
        doc = json.loads(text)
        node = doc
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
        return json.dumps(doc, indent=1, sort_keys=True) + "\n"

    bad_checksum = sc0.manifest.authority[:-1] + ("a" if sc0.manifest.authority[-1] != "a" else "b")
    every = ["V1", "V2", "V3", "V4", "V5", "V6"]

    r = world.rendition
    cases = [
        case("L0 authority, full image", write_png(ev0), sc0.to_text(), None, "default", "ACCEPT", []),
        case("L1 lab, tile 5 hidden", write_png(ev1), sc1.to_text(), None, "default", "ACCEPT", []),
        case("L1 lab, sidecar embedded in the PNG (no external file)", write_png(ev1, sc1.to_text()), None, None,
             "default", "ACCEPT", []),
        case("L2 newsroom with rendition", write_png(ev2), sc2.to_text(), write_png(r), "default", "ACCEPT", []),
        case("flipped visible pixel", _variant(ev2, 0), sc2.to_text(), None, "default", "REJECT", ["V3"]),
        case("hidden tile not black", _variant(ev1, (70 * 200 + 70) * 3, 200), sc1.to_text(), None, "default",
             "REJECT", ["V3"]),
        case("tampered rendition", write_png(ev2), sc2.to_text(),
             write_png(Image(r.width, r.height, bytes([r.rgb[0] ^ 1]) + r.rgb[1:])), "default", "REJECT", ["V6"]),
        case("authority not in trust list", write_png(ev0), sc0.to_text(), None, "empty", "REJECT", ["V1"]),
        case("authority revoked before signing", write_png(ev0), sc0.to_text(), None, "revoked", "REJECT", ["V2"]),
        case("level anchored by another account", write_png(ev_bad), sc_bad.to_text(), None, "default",
             "REJECT", ["V4"]),
        case("level paired with another level's anchor", write_png(ev2),
             replace(sc2, level_tx=sc1.level_tx).to_text(), None, "default", "REJECT", ["V4"]),
        case("APNG frame added to a valid L1 (acTL)", _with_chunk(write_png(ev1, sc1.to_text()),
             chunk(b"acTL", struct.pack(">II", 2, 0))), None, None, "default", "REJECT", ["V3"]),
        case("tRNS makes the black tiles transparent", _with_chunk(write_png(ev1, sc1.to_text()),
             chunk(b"tRNS", bytes(6))), None, None, "default", "REJECT", ["V3"]),
        case("two embedded sidecars never fall back to the external file",
             _with_chunk(write_png(ev1, sc1.to_text()), _sidecar_chunk(write_png(ev1, sc1.to_text()))),
             sc1.to_text(), None, "default", "REJECT", ["V1", "V2", "V3", "V4", "V5", "V6"]),
        case("float in sidecar JSON", write_png(ev1), sc1.to_text().replace('"velum": 1', '"velum": 1.0'), None,
             "default", "REJECT", ["V1", "V2", "V3", "V4", "V5", "V6"]),
        # parity cases: each gave another verdict or other failed checks in velum-js before the audit
        case("same authority also listed for mainnet, first", write_png(ev0), sc0.to_text(), None,
             "mainnet-listed-first", "ACCEPT", []),
        case("manifest above 2^25 pixels (8192 x 8192)", write_png(ev0),
             edited(edited(sc0.to_text(), "manifest", "w", value=8192), "manifest", "h", value=8192), None,
             "default", "REJECT", every),
        case("authority address with a wrong checksum", write_png(ev0),
             edited(sc0.to_text(), "manifest", "authority", value=bad_checksum), None, "default", "REJECT", every),
        case("crop beyond the largest grid", write_png(ev1),
             edited(sc1.to_text(), "level", "crop", value=[20000, 0, 1, 1]), None, "default", "REJECT", every),
        case("crop with zero columns", write_png(ev1), edited(sc1.to_text(), "level", "crop", value=[0, 0, 0, 1]),
             None, "default", "REJECT", ["V4", "V5"]),
        case("level points to another manifest anchor, ledger down", write_png(ev1),
             edited(sc1.to_text(), "level", "manifest_tx", value=sc1.level_tx), None, "default", "REJECT", ["V4"],
             unknown=("V2",), ledger="down"),
    ]

    ledger = {h: {"validated": t.validated, "result": t.result, "tx_type": t.tx_type, "account": t.account,
                  "memos": [[mt, md.hex()] for mt, md in t.memos], "ledger_index": t.ledger_index,
                  "close_time": t.close_time} for h, t in sorted(world.ledger.txs.items())}

    small = Image(7, 5, gradient(7, 5))
    row = Image(3, 1, bytes(v for v in (0, 30, 60) for _ in range(3)))
    recipes: list[tuple[str, Image, tuple[int, int, int, int] | None, Recipe | None]] = [
        ("rotate 90", small, None, Recipe(rotate=90)),
        ("rotate 180", small, None, Recipe(rotate=180)),
        ("rotate 270", small, None, Recipe(rotate=270)),
        ("resize 3x1 -> 2x1 (fractional weights)", row, None, Recipe(resize=(2, 1))),
        ("resize 7x5 -> 3x2", small, None, Recipe(resize=(3, 2))),
        ("brightness -40 contrast 90", small, None, Recipe(brightness=-40, contrast=90)),
        ("crop and recipe of L2", ev2, sc2.level.crop, sc2.level.recipe),
    ]
    return {
        "version": 1,
        "about": ("VELUM levels (redacted copies), ledger dump, attacks and recipe cases. Cases name PNGs by SHA-256 (hex); "
                  "the base64 bytes are in png_files. Generated by scripts/make_vectors.py."),
        "trust_lists": trust_lists,
        "ledger": ledger,
        "cases": cases,
        "recipe": [{"name": name, "input_png_b64": b64(write_png(img)), "crop": list(crop) if crop else None,
                    "recipe": rec.to_json() if rec else None, "output_png_b64": b64(write_png(render(img, crop, rec)))}
                   for name, img, crop, rec in recipes],
        "png_files": files,
        "bitmap": [{"n": n, "hidden": sorted(h), "hex": encode_bitmap(frozenset(h), n)}
                   for n, h in ((10, {0, 9}), (12, {5, 6}), (240, {0, 7, 8, 239}), (1, set()))],
    }


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(build(), indent=1, sort_keys=True) + "\n", encoding="ascii")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size} bytes)")
    LEVELS_OUT.write_text(json.dumps(build_levels(), indent=1, sort_keys=True) + "\n", encoding="ascii")
    print(f"wrote {LEVELS_OUT.relative_to(ROOT)} ({LEVELS_OUT.stat().st_size} bytes)")
