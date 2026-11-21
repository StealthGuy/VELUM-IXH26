"""The verifier on the reference copies: every honest level ACCEPTs, every attack REJECTs at the right check."""
from __future__ import annotations

from dataclasses import replace

import pytest

from helpers import chunk
from scenario import AUTHORITY, K, LAB, NEWSROOM, STRANGER, World, build
from velum import manifest as mf
from velum import pq
from velum.descriptor import MEMO_TYPE as LEVEL_MEMO
from velum.descriptor import Descriptor, Recipe
from velum.image import Image
from velum.ledger import LedgerTx
from velum.level import Disclosure, commit, from_master, redact, release_level, release_master
from velum.png import write_png
from velum.recipe import render
from velum.sidecar import Sidecar
from velum.trust import Authority
from velum.verify import ACCEPT, REJECT, UNVERIFIABLE, Report, verify


@pytest.fixture(scope="module")
def world() -> World:
    return build()


def check(world: World, level: int, evidence: Image | None = None, sidecar: Sidecar | str | None = None,
          rendition: bytes | None = None, trust: list[Authority] | None = None) -> Report:
    ev, sc = world.levels[level]
    text = sidecar if isinstance(sidecar, str) else (sidecar or sc).to_text()
    return verify(write_png(evidence or ev), text, world.trust if trust is None else trust, world.ledger, rendition)


def failed(report: Report) -> list[str]:
    return [c.id for c in report.checks if not c.ok]


# ---------------------------------------------------------------- honest copies
def test_every_level_verifies(world: World) -> None:
    for level in range(3):
        report = check(world, level)
        assert report.status == ACCEPT, report.lines()
    report = check(world, 2, rendition=write_png(world.rendition))
    assert report.status == ACCEPT, report.lines()
    assert (world.rendition.width, world.rendition.height) == (50, 77)


def test_report_facts(world: World) -> None:
    facts = check(world, 2).facts
    assert facts["authority"] == "Test Authority"
    assert facts["published_by"] == NEWSROOM and check(world, 0).facts["published_by"] == AUTHORITY
    # L2 hides 5, 6 and everything outside the 3 x 2 crop (3, 7, 8, 9, 10, 11); grid 4 x 3
    assert facts["mask"] == ["...#", ".###", "####"]
    assert 0 < facts["hidden_percent"] < 100  # type: ignore[operator]


def test_redaction_really_hides(world: World) -> None:
    ev2, sc2 = world.levels[2]
    assert 5 not in sc2.visible and 6 not in sc2.visible  # salts dropped
    x0, y0 = 64, 64  # tile 5 = column 1, row 1
    assert ev2.pixel(x0, y0) == (0, 0, 0) and world.original.pixel(x0, y0) != (0, 0, 0)


def test_metadata_chunks_are_outside_the_signature(world: World) -> None:
    """Documented in docs/VELUM.md 8.3: extra PNG chunks do not change pixels, so verification passes."""
    png = write_png(world.levels[1][0])
    tagged = png[:-12] + chunk(b"tEXt", b"Comment\x00not signed") + png[-12:]
    _, sc = world.levels[1]
    assert verify(tagged, sc.to_text(), world.trust, world.ledger).status == ACCEPT


# ---------------------------------------------------------------- attacks on pixels (V3, V6)
def test_flipped_visible_pixel(world: World) -> None:
    ev = world.levels[2][0]
    rgb = bytearray(ev.rgb)
    rgb[0] ^= 1
    assert failed(check(world, 2, evidence=Image(ev.width, ev.height, bytes(rgb)))) == ["V3"]


def test_hidden_tile_not_black(world: World) -> None:
    ev = world.levels[1][0]
    rgb = bytearray(ev.rgb)
    rgb[(70 * ev.width + 70) * 3] = 200  # inside hidden tile 5
    assert failed(check(world, 1, evidence=Image(ev.width, ev.height, bytes(rgb)))) == ["V3"]


def test_unredacting_without_the_master_fails(world: World) -> None:
    """Claim tile 5 of L1 is visible, with a guessed salt and the original pixels: the root breaks,
    and the bitmap still says hidden."""
    ev1, sc1 = world.levels[1]
    forged = replace(sc1, visible={**sc1.visible, 5: bytes(32)}, hidden={})
    report = check(world, 1, evidence=world.original, sidecar=forged)
    assert "V3" in failed(report) and "V5" in failed(report)


def test_tampered_rendition(world: World) -> None:
    r = world.rendition
    bad = Image(r.width, r.height, bytes([r.rgb[0] ^ 1]) + r.rgb[1:])
    assert failed(check(world, 2, rendition=write_png(bad))) == ["V6"]


def test_wrong_size_evidence(world: World) -> None:
    ev = world.levels[0][0]
    small = Image(ev.width - 1, ev.height, b"".join(ev.row(y)[:-3] for y in range(ev.height)))
    assert "V3" in failed(check(world, 0, evidence=small))


# ---------------------------------------------------------------- attacks on trust and anchors (V1, V2, V4)
def test_impostor_authority_key(world: World) -> None:
    """Same address, another ML-DSA key: the trust list pins the real key."""
    _, sc = world.levels[0]
    pk, sk = pq.keypair(bytes([9]) * 32)
    forged = replace(sc, authority_pk=pk, manifest_sig=mf.sign(sc.manifest, sk))
    assert "V1" in failed(check(world, 0, sidecar=forged))


def test_untrusted_authority(world: World) -> None:
    assert failed(check(world, 0, trust=[])) == ["V1"]


def test_trust_entry_counts_only_on_its_network(world: World) -> None:
    mainnet_only = [replace(world.trust[0], network="mainnet")]
    assert failed(check(world, 0, trust=mainnet_only)) == ["V1"]


def test_revoked_authority(world: World) -> None:
    revoked = [replace(world.trust[0], not_after=1_800_000_000)]  # before the signing time
    assert failed(check(world, 0, trust=revoked)) == ["V2"]


def test_manifest_anchored_by_another_account(world: World) -> None:
    ev0, sc0 = world.levels[0]
    tx = world.ledger.anchor(STRANGER, mf.MEMO_TYPE, mf.memo_data(sc0.manifest, sc0.manifest_sig))
    assert "V2" in failed(check(world, 0, sidecar=replace(sc0, manifest_tx=tx)))


def test_level_anchored_by_someone_else_than_its_producer(world: World) -> None:
    ev0, sc0 = world.levels[0]
    d = Descriptor(sc0.manifest_tx, LAB, 12, frozenset({1}))
    tx = world.ledger.anchor(STRANGER, LEVEL_MEMO, d.memo_data())  # claims LAB, sent by STRANGER
    ev, sc = release_level(ev0, sc0, d, tx)
    assert failed(check(world, 0, evidence=ev, sidecar=sc)) == ["V4"]


@pytest.mark.parametrize("bad", [{"result": "tecNO_PERMISSION"}, {"tx_type": "Payment"},
                                 {"extra_memos": [("velum/level", bytes(32))]}])
def test_level_anchor_that_is_not_a_clean_anchor(world: World, bad: dict[str, object]) -> None:
    """"Anchored" means a tesSUCCESS AccountSet with exactly one memo (docs/VELUM.md section 7)."""
    ev0, sc0 = world.levels[0]
    d = Descriptor(sc0.manifest_tx, LAB, 12, frozenset({1}))
    ev, sc = release_level(ev0, sc0, d, world.ledger.anchor(LAB, LEVEL_MEMO, d.memo_data(), **bad))  # type: ignore[arg-type]
    report = check(world, 0, evidence=ev, sidecar=sc)
    assert report.status == REJECT and failed(report) == ["V4"]


def test_level_anchored_under_the_manifest_memo_type(world: World) -> None:
    ev0, sc0 = world.levels[0]
    d = Descriptor(sc0.manifest_tx, LAB, 12, frozenset({1}))
    ev, sc = release_level(ev0, sc0, d, world.ledger.anchor(LAB, mf.MEMO_TYPE, d.memo_data()))
    report = check(world, 0, evidence=ev, sidecar=sc)
    assert failed(report) == ["V4"] and "memo type" in report.checks[3].detail


def test_level_anchored_before_its_manifest(world: World) -> None:
    ev0, sc0 = world.levels[0]
    d = Descriptor(sc0.manifest_tx, LAB, 12, frozenset({1}))
    ev, sc = release_level(ev0, sc0, d, world.ledger.anchor(LAB, LEVEL_MEMO, d.memo_data()))
    old = world.ledger.txs[sc.level_tx]
    world.ledger.txs[sc.level_tx] = replace(old, ledger_index=world.ledger.txs[sc0.manifest_tx].ledger_index - 1)
    report = check(world, 0, evidence=ev, sidecar=sc)
    assert failed(report) == ["V4"] and "before the manifest" in report.checks[3].detail


def test_level_paired_with_another_levels_anchor(world: World) -> None:
    _, sc1 = world.levels[1]
    _, sc2 = world.levels[2]
    assert failed(check(world, 2, sidecar=replace(sc2, level_tx=sc1.level_tx))) == ["V4"]


def test_crop_that_does_not_hide(world: World) -> None:
    ev0, sc0 = world.levels[0]
    d = Descriptor(sc0.manifest_tx, LAB, 12, frozenset(), crop=(0, 0, 1, 1))
    ev, sc = release_level(ev0, sc0, d, world.ledger.anchor(LAB, LEVEL_MEMO, d.memo_data()))
    assert failed(check(world, 0, evidence=ev, sidecar=sc)) == ["V5"]


def test_forged_sidecar_json(world: World) -> None:
    text = world.levels[1][1].to_text().replace('"velum": 1', '"velum": 1.0')
    report = check(world, 1, sidecar=text)
    assert report.status == REJECT and failed(report) == ["V1", "V2", "V3", "V4", "V5", "V6"]


# ---------------------------------------------------------------- the network is not a forgery
def test_unreachable_ledger_is_unverifiable(world: World) -> None:
    world.ledger.down = True
    try:
        report = check(world, 1)
    finally:
        world.ledger.down = False
    assert report.status == UNVERIFIABLE and set(failed(report)) == {"V2", "V4"}


def test_manifest_from_another_image_does_not_open(world: World) -> None:
    """A valid, anchored manifest of a different image cannot be paired with this evidence."""
    other = Image(200, 130, bytes(200 * 130 * 3))
    m = mf.Manifest(200, 130, commit(other, K), AUTHORITY)
    sig = mf.sign(m, world.sk)
    m_tx = world.ledger.anchor(AUTHORITY, mf.MEMO_TYPE, mf.memo_data(m, sig))
    d0 = from_master(m, m_tx)
    _, sc_other = release_master(other, K, m, sig, world.pk, m_tx, d0,
                                 world.ledger.anchor(AUTHORITY, LEVEL_MEMO, d0.memo_data()))
    assert failed(check(world, 0, sidecar=sc_other)) == ["V3"]


# ---------------------------------------------------------------- review fixes
def test_unexpected_errors_fail_closed(world: World) -> None:
    class Broken:
        network = "testnet"

        def transaction(self, tx_hash: str) -> LedgerTx:
            raise RuntimeError("bug in a ledger client")

    ev, sc = world.levels[0]
    report = verify(write_png(ev), sc.to_text(), world.trust, Broken())
    assert report.status == REJECT and "internal error" in report.checks[1].detail


def test_recipe_must_be_applicable_even_without_a_rendition(world: World) -> None:
    ev0, sc0 = world.levels[0]
    d = Descriptor(sc0.manifest_tx, LAB, 12, frozenset(), recipe=Recipe(resize=(400, 10)))
    ev, sc = release_level(ev0, sc0, d, world.ledger.anchor(LAB, LEVEL_MEMO, d.memo_data()))
    report = check(world, 0, evidence=ev, sidecar=sc)
    assert failed(report) == ["V5"] and "only shrinking" in report.checks[4].detail


def test_redact_rejects_unknown_tiles(world: World) -> None:
    ev0, sc0 = world.levels[0]
    with pytest.raises(ValueError, match="not in this level"):
        redact(ev0, Disclosure(sc0.visible, sc0.hidden), frozenset({99}))


def test_a_copy_cannot_reveal_what_its_source_hid(world: World) -> None:
    """LAB's copy hides tile 5. Describing a copy of it without tile 5 hidden does not reveal it:
    the sidecar still lists tile 5 as hidden (no salt exists), so the bitmap disagrees (V5)."""
    ev1, sc1 = world.levels[1]
    d = Descriptor(sc1.manifest_tx, NEWSROOM, 12, frozenset())
    ev, sc = release_level(ev1, sc1, d, world.ledger.anchor(NEWSROOM, LEVEL_MEMO, d.memo_data()))
    assert 5 in sc.hidden and failed(check(world, 1, evidence=ev, sidecar=sc)) == ["V5"]


# ---------------------------------------------------------------- embedded sidecar
def test_the_png_alone_is_enough(world: World) -> None:
    ev, sc = world.levels[2]
    report = verify(write_png(ev, sc.to_text()), None, world.trust, world.ledger, write_png(world.rendition))
    assert report.status == ACCEPT and report.facts["sidecar"] == "embedded in the PNG"


def test_external_sidecar_when_the_png_has_none(world: World) -> None:
    ev, sc = world.levels[1]
    report = verify(write_png(ev), sc.to_text(), world.trust, world.ledger)
    assert report.status == ACCEPT and report.facts["sidecar"] == "external file"


def test_no_sidecar_anywhere(world: World) -> None:
    report = verify(write_png(world.levels[0][0]), None, world.trust, world.ledger)
    assert report.status == REJECT and "no sidecar" in report.checks[0].detail


def test_embedded_sidecar_wins_and_is_still_fully_checked(world: World) -> None:
    ev1, sc1 = world.levels[1]
    _, sc2 = world.levels[2]
    # embedded L2 sidecar on L1's evidence: it wins over the correct external file, and does not verify
    report = verify(write_png(ev1, sc2.to_text()), sc1.to_text(), world.trust, world.ledger)
    assert report.status == REJECT and report.facts["sidecar"] == "embedded in the PNG"


def test_corrupt_evidence_is_a_pixel_failure_when_the_sidecar_is_external(world: World) -> None:
    _, sc = world.levels[1]
    report = verify(b"not a png at all", sc.to_text(), world.trust, world.ledger)
    assert failed(report) == ["V3"] and "PNG" in report.checks[2].detail


# ---------------------------------------------------------------- audit fixes
def _insert(png: bytes, *chunks: bytes) -> bytes:
    """Put chunks right after IHDR (8-byte signature + 25-byte IHDR chunk)."""
    return png[:33] + b"".join(chunks) + png[33:]


def test_apng_frame_or_transparent_black_cannot_ride_along(world: World) -> None:
    """H2: the audit's proof of concept. A second APNG frame, or tRNS making black transparent, changes what
    a browser shows without touching IDAT: the verifier must refuse them."""
    ev, sc = world.levels[1]
    png = write_png(ev, sc.to_text())
    actl = chunk(b"acTL", (2).to_bytes(4, "big") + bytes(4))
    trns = chunk(b"tRNS", bytes(6))  # (0, 0, 0) transparent: every hidden tile shows the page through
    for forged in (_insert(png, actl), _insert(png, trns), _insert(png, chunk(b"iCCP", b"p\x00\x00x"))):
        report = verify(forged, None, world.trust, world.ledger)
        assert failed(report) == ["V3"] and "not allowed" in report.checks[2].detail


def test_rendition_with_a_colour_profile_is_refused(world: World) -> None:
    rendition = _insert(write_png(world.rendition), chunk(b"gAMA", (45455).to_bytes(4, "big")))
    assert failed(check(world, 2, rendition=rendition)) == ["V6"]


def test_broken_embedded_sidecar_never_falls_back(world: World) -> None:
    """M1: two velum.sidecar chunks plus a valid external file used to ACCEPT with the external file."""
    ev, sc = world.levels[1]
    one = write_png(ev, sc.to_text())
    ztxt = one[33:one.index(b"IDAT") - 4]
    report = verify(one[:33] + ztxt + one[33:], sc.to_text(), world.trust, world.ledger)
    assert report.status == REJECT and failed(report)[0] == "V1" and "more than one" in report.checks[0].detail


def test_external_sidecar_that_differs_is_reported(world: World) -> None:
    ev, sc = world.levels[1]
    report = verify(write_png(ev, sc.to_text()), world.levels[2][1].to_text(), world.trust, world.ledger)
    assert report.status == ACCEPT and "differs" in str(report.facts["sidecar_note"])


@pytest.mark.parametrize("text", ["[" * 100_000, '{"velum":' + "9" * 5000 + "}"])
def test_hostile_sidecar_is_a_reject_not_a_crash(world: World, text: str) -> None:
    """M2: these used to escape verify() as ValueError / RecursionError."""
    report = verify(write_png(world.levels[0][0]), text, world.trust, world.ledger)
    assert report.status == REJECT and failed(report)[0] == "V1"
    report = verify(write_png(world.levels[0][0], text), None, world.trust, world.ledger)
    assert report.status == REJECT and failed(report)[0] == "V1"


def test_non_ascii_external_sidecar_is_a_reject(world: World) -> None:
    report = verify(write_png(world.levels[0][0]), b"\xff\xfe{}", world.trust, world.ledger)
    assert report.status == REJECT and "not ASCII" in report.checks[0].detail


def test_pixel_budget(world: World) -> None:
    """M5: the verifier refuses, before inflating, images above its budget."""
    ev, sc = world.levels[0]
    report = verify(write_png(ev, sc.to_text()), None, world.trust, world.ledger, max_pixels=ev.width * ev.height - 1)
    assert failed(report) == ["V3"]
    assert "budget" in report.checks[2].detail


def test_image_above_the_budget_is_unverifiable_not_forged(world: World) -> None:
    ev, sc = world.levels[0]  # 200 x 130 = 26 000 pixels, authentic
    report = verify(write_png(ev, sc.to_text()), None, world.trust, world.ledger, max_pixels=10_000)
    assert report.status == UNVERIFIABLE and failed(report) == ["V3"]
    assert "budget" in report.checks[2].detail and report.checks[2].inconclusive


def test_over_budget_evidence_with_rendition(world: World) -> None:
    ev, sc = world.levels[2]
    evidence = write_png(ev, sc.to_text())
    report = verify(evidence, None, world.trust, world.ledger, write_png(world.rendition), max_pixels=10_000)
    assert report.status == UNVERIFIABLE and failed(report) == ["V3", "V6"]
    report = verify(evidence, None, world.trust, world.ledger, b"invalid PNG", max_pixels=10_000)
    assert report.status == REJECT and not report.checks[-1].inconclusive


def test_over_budget_evidence_with_a_rendition_is_unverifiable_not_forged(world: World) -> None:
    """V6 cannot be decided without the evidence, so it is inconclusive like V3, never a failure."""
    ev, sc = world.levels[-1]
    rendition = write_png(render(ev, sc.level.crop, sc.level.recipe))
    report = verify(write_png(ev, sc.to_text()), None, world.trust, world.ledger, rendition, max_pixels=10_000)
    assert report.status == UNVERIFIABLE and failed(report) == ["V3", "V6"]
    assert report.checks[2].inconclusive and report.checks[5].inconclusive
