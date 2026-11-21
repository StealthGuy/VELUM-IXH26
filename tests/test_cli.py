"""Command-line helpers that need no network: tile selection, level files, report text."""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

import pytest

from scenario import AUTHORITY, build
from velum import cli, config
from velum.cli import (EXIT_ACCEPT, EXIT_ERROR, EXIT_REJECT, EXIT_UNVERIFIABLE, check_name, ensure_free, load_level,
                       main, master_path, paths, report_text, save_level, tile_set, verified_source, write_master)
from velum.descriptor import Recipe
from velum.image import Image
from velum.png import MAX_SIDECAR, write_png
from velum.tiles import Grid
from velum.verify import verify


def test_tile_selection() -> None:
    g = Grid(1280, 720)  # 20 x 12
    assert tile_set(g, "29,49", []) == {29, 49}
    assert tile_set(g, None, ["8:9:10:10"]) == {188, 189, 190, 208, 209, 210}  # the demo's password card
    assert tile_set(g, "1", ["0:0:0:1"]) == {0, 1, 20}


def test_level_files_roundtrip(tmp_path: Path) -> None:
    world = build()
    for k, (ev, sc) in enumerate(world.levels):
        stem = tmp_path / f"l{k}"
        rendition = save_level(stem, ev, sc)
        assert load_level(stem) == (ev, sc)
        assert (rendition is not None) == (k == 2)  # only L2 has a crop and a recipe
    assert paths(tmp_path / "l2")[2].read_bytes()  # the public rendition was written


def test_report_text_shows_the_facts() -> None:
    world = build()
    ev, sc = world.levels[2]
    text = report_text(verify(write_png(ev), sc.to_text(), world.trust, world.ledger))
    assert "VELUM verdict: ACCEPT" in text and "published_by" in text and "mask (# hidden):" in text


def test_level_loads_from_the_png_when_the_json_is_gone(tmp_path: Path) -> None:
    world = build()
    ev, sc = world.levels[1]
    stem = tmp_path / "l1"
    save_level(stem, ev, sc)
    paths(stem)[1].unlink()  # delete l1.velum.json: the PNG still carries the sidecar
    assert load_level(stem) == (ev, sc)


# ---------------------------------------------------------------- review fixes
def test_tile_selection_refuses_anything_outside_the_grid() -> None:
    g = Grid(1280, 720)  # 20 x 12
    for singles, rects in ((None, ["18:0:21:0"]),   # columns past the edge used to wrap into the next row
                           (None, ["0:11:0:12"]),   # row 12 does not exist
                           (None, ["5:0:4:0"]),     # start after end
                           ("240", []),             # tile 240 does not exist
                           ("-1", [])):
        with pytest.raises(ValueError):
            tile_set(g, singles, rects)
    with pytest.raises(ValueError):
        tile_set(g, None, ["a:b:c:d"])


def test_existing_files_are_never_overwritten_silently(tmp_path: Path) -> None:
    stem = tmp_path / "l0"
    ensure_free(stem, force=False)  # nothing there yet
    write_master(stem, bytes(32), bytes(32), force=False)
    with pytest.raises(FileExistsError, match="--force"):
        ensure_free(stem, force=False)
    with pytest.raises(FileExistsError):
        write_master(stem, bytes(32), bytes(32), force=False)  # the first image's K must survive


def test_master_is_private_from_the_first_byte(tmp_path: Path) -> None:
    stem = tmp_path / "l0"
    master_path(stem).write_text("old")
    os.chmod(master_path(stem), 0o644)  # even if an old file was readable...
    write_master(stem, bytes(range(32)), bytes(32), force=True)
    assert stat.S_IMODE(master_path(stem).stat().st_mode) == 0o600  # ...the new one is 600
    assert json.loads(master_path(stem).read_text())["K"] == bytes(range(32)).hex()
    backup, = master_path(stem).parent.glob("*.replaced-*.master.json")
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600


def test_errors_are_messages_not_tracebacks(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["verify", str(tmp_path / "missing")]) == EXIT_ERROR
    assert "error:" in capsys.readouterr().err
    assert main(["derive", str(tmp_path / "l1"), "--as", "LAB", "--name", "l1"]) == EXIT_ERROR  # same as source
    with pytest.raises(SystemExit) as usage:
        main(["derive"])  # argparse: usage error
    assert usage.value.code == 2  # 2 is argparse's; UNVERIFIABLE is 3


def test_verify_exit_codes_do_not_collide() -> None:
    assert len({EXIT_ACCEPT, EXIT_REJECT, 2, EXIT_UNVERIFIABLE, EXIT_ERROR}) == 5


# ---------------------------------------------------------------- audit fixes
def test_master_lives_apart_and_is_never_deleted(tmp_path: Path, private_master_dir: Path) -> None:
    """M4: K is not next to the level files, and replacing it moves the old one aside."""
    stem = tmp_path / "case" / "l0"
    write_master(stem, bytes(range(32)), bytes(32), force=False)
    assert master_path(stem).parent == private_master_dir and not list((tmp_path / "case").glob("*"))
    with pytest.raises(FileExistsError, match="--replace-master"):
        ensure_free(stem, force=True)  # --force alone no longer reaches the master
    ensure_free(stem, force=True, replace_master=True)
    write_master(stem, bytes(32), bytes(32), force=True)
    kept = [p for p in private_master_dir.iterdir() if ".replaced-" in p.name]
    assert len(kept) == 1 and json.loads(kept[0].read_text())["K"] == bytes(range(32)).hex()
    assert json.loads(master_path(stem).read_text())["K"] == bytes(32).hex()


def test_dotted_names_do_not_land_on_other_files(tmp_path: Path) -> None:
    """L2: with_suffix used to turn l1.final into l1.png."""
    assert paths(tmp_path / "l1.final")[0].name == "l1.final.png"
    with pytest.raises(ValueError, match="no dots"):
        check_name("l1.final")
    assert main(["derive", str(tmp_path / "l0"), "--as", "LAB", "--name", "l1.final"]) == EXIT_ERROR


def test_derive_refuses_a_source_that_does_not_verify(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                      capsys: pytest.CaptureFixture[str]) -> None:
    """L1: a tampered source is refused before anything is anchored."""
    world = build()
    ev, sc = world.levels[1]
    rgb = bytearray(ev.rgb)
    rgb[0] ^= 1
    save_level(tmp_path / "l1", Image(ev.width, ev.height, bytes(rgb)), sc)
    trust = tmp_path / "trust.json"
    trust.write_text(json.dumps([{"name": "Test Authority", "network": "testnet", "xrpl_address": AUTHORITY,
                                  "mldsa44_pk_sha256": hashlib.sha256(world.pk).hexdigest(), "not_after": None}]))
    monkeypatch.setattr(cli, "XrplLedger", lambda: world.ledger)
    anchored: list[object] = []
    monkeypatch.setattr(cli, "anchor", lambda *args: anchored.append(args))
    code = main(["derive", str(tmp_path / "l1"), "--as", "LAB", "--name", "l2", "--hide", "1",
                 "--trust", str(trust)])
    assert code == EXIT_ERROR and anchored == [] and "does not verify (REJECT)" in capsys.readouterr().err
    with pytest.raises(ValueError, match="REJECT"):
        verified_source(tmp_path / "l1", trust)


def test_verify_command_rejects_a_non_ascii_sidecar_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """L4: used to crash with UnicodeDecodeError (exit 4)."""
    world = build()
    ev, sc = world.levels[0]
    stem = tmp_path / "l0"
    paths(stem)[0].write_bytes(write_png(ev))  # no embedded sidecar
    paths(stem)[1].write_bytes(b"\xff" + sc.to_text().encode())
    trust = tmp_path / "trust.json"
    trust.write_text("[]")
    monkeypatch.setattr(cli, "XrplLedger", lambda: world.ledger)
    assert main(["verify", str(stem), "--trust", str(trust)]) == EXIT_REJECT


def test_sign_refuses_an_image_default_verifiers_could_not_check(tmp_path: Path,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    from velum import config
    from velum.cli import sign_image
    from velum.image import Image

    monkeypatch.setattr(config, "max_verify_pixels", lambda: 10)
    with pytest.raises(ValueError, match="verification budget"):
        sign_image(Image(4, 4, bytes(48)), tmp_path / "l0")  # refused before any wallet or anchor


def test_verified_source_keeps_checked_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    world = build()
    stem = tmp_path / "case"
    original = world.levels[0]
    save_level(stem, *original)
    trust = tmp_path / "trust.json"
    trust.write_text("[]")
    monkeypatch.setattr(cli, "parse_trust_list", lambda text: world.trust)

    def replace_files() -> object:
        save_level(stem, *world.levels[1])
        return world.ledger

    monkeypatch.setattr(cli, "XrplLedger", replace_files)
    assert verified_source(stem, trust) == original
    assert load_level(stem) == world.levels[1]


def test_external_size_limit_applies_only_to_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    world = build()
    stem = tmp_path / "case"
    ev, sc = world.levels[0]
    save_level(stem, ev, sc)
    evidence, external, _ = paths(stem)
    # Whitespace after valid JSON also counts toward the size limit.
    external.write_bytes(sc.to_text().encode().ljust(MAX_SIDECAR + 1, b" "))
    trust = tmp_path / "trust.json"
    trust.write_text("[]")
    monkeypatch.setattr(cli, "parse_trust_list", lambda text: world.trust)
    monkeypatch.setattr(cli, "XrplLedger", lambda: world.ledger)
    report = cli.verify_files(stem, trust)
    assert report.status == "ACCEPT" and "sidecar_note" in report.facts
    evidence.write_bytes(write_png(ev))
    report = cli.verify_files(stem, trust)
    assert report.status == "REJECT" and "exceeds" in report.checks[0].detail


def test_invalid_recipe_stops_before_anchor_or_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from xrpl.wallet import Wallet

    source = build().levels[0]
    monkeypatch.setattr(config, "wallet", lambda role: Wallet.create())
    monkeypatch.setattr(cli, "anchor", lambda *args: pytest.fail("unexpected anchor"))
    stem = tmp_path / "derived"
    with pytest.raises(ValueError, match="only shrinking"):
        cli.derive(source, "LAB", stem, crop=(0, 0, 2, 1), recipe=Recipe(rotate=90, resize=(65, 100)))
    with pytest.raises(ValueError, match="crop"):
        cli.derive(source, "LAB", stem, crop=(-1, 0, 1, 1))
    assert all(not path.exists() for path in paths(stem))


def test_derive_refuses_a_recipe_v5_would_reject_before_anchoring(tmp_path: Path,
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    """A resize that enlarges can never verify: it must fail before the anchor, not after it."""
    world = build()
    anchored: list[object] = []
    monkeypatch.setattr(cli, "anchor", lambda *args: anchored.append(args))
    monkeypatch.setattr(config, "wallet", lambda role: type("W", (), {"address": AUTHORITY})())
    ev, sc = world.levels[1]
    bigger = Recipe(rotate=0, resize=(ev.width * 2, ev.height * 2), brightness=0, contrast=0)
    with pytest.raises(ValueError, match="shrink"):
        cli.derive((ev, sc), "LAB", tmp_path / "l2", recipe=bigger)
    assert anchored == [] and not any(p.exists() for p in paths(tmp_path / "l2"))
