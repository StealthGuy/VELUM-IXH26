"""Command line: velum sign | derive | verify (docs/VELUM.md; no frontend).

    velum sign   samples/photo.png --out out/case --name l0
    velum derive out/case/l0 --as LAB --name l1 --hide-rect 8:9:10:10
    velum derive out/case/l1 --as NEWSROOM --name l2 --hide 6,7,8 --resize 640x360 --brightness 8
    velum verify out/case/l2

A level is named by its stem: STEM.png (evidence, with the sidecar embedded in a zTXt chunk), STEM.velum.json
(the same sidecar as a separate file, used when a PNG carries none), STEM.public.png (rendition, written when
the level has a crop or a recipe). Wallets and keys come from .env.local (`--as ROLE`): secrets are never
accepted on the command line. `sign` first writes the authority's per-image secret K to a private folder,
never next to the level files (VELUM_MASTER_DIR, default ~/.velum/masters; folder mode 700, file mode 600).
Existing files are never overwritten unless `--force` is given, and a master is never deleted: replacing
one needs `--replace-master` too and moves the old one aside. `derive` refuses a source that does not
verify: a producer never anchors a copy of something it has not checked.

Exit codes: 0 ACCEPT, 1 REJECT, 2 usage error (argparse), 3 UNVERIFIABLE, 4 any other error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from . import config, pq
from . import manifest as mf
from .descriptor import MEMO_TYPE as LEVEL_MEMO
from .descriptor import Recipe
from .image import Image
from .level import commit, from_level, from_master, release_level, release_master
from .png import MAX_SIDECAR, read_png, read_sidecar, write_png
from .recipe import output_size, render
from .sidecar import Sidecar
from .tiles import Grid
from .trust import Authority, parse_trust_list
from .verify import ACCEPT, REJECT, UNVERIFIABLE, Report, verify
from .xrpl_ledger import XrplLedger, anchor

EXIT_ACCEPT, EXIT_REJECT, EXIT_UNVERIFIABLE, EXIT_ERROR = 0, 1, 3, 4


# ---------------------------------------------------------------- files
def paths(stem: Path) -> tuple[Path, Path, Path]:
    """(evidence, sidecar, rendition) of a level stem. Suffixes are appended, never substituted, so a
    stem with a dot cannot land on another level's files."""
    return (stem.with_name(stem.name + ".png"), stem.with_name(stem.name + ".velum.json"),
            stem.with_name(stem.name + ".public.png"))


def check_name(name: str) -> str:
    """A new level's name: no dots or separators (l1.final would read as l1 plus a suffix elsewhere)."""
    if not name or any(ch in name for ch in "./\\") or name.startswith("-"):
        raise ValueError(f"level name {name!r}: use letters, digits, '-' or '_' (no dots or slashes)")
    return name


def master_path(stem: Path) -> Path:
    """Where the secret K of the image signed as `stem` lives: a private folder, never next to the files
    that get shared. The name keeps the stem for humans and a hash of its full path for uniqueness."""
    tag = hashlib.sha256(str(stem.resolve()).encode()).hexdigest()[:16]
    return config.master_dir() / f"{stem.name}-{tag}.master.json"


def ensure_free(stem: Path, force: bool, replace_master: bool = False) -> None:
    """Refuse to overwrite a level unless forced, and the secret of an image already signed unless
    `replace_master` too: losing K means never releasing another level of that image."""
    taken = [p for p in (*paths(stem), master_path(stem)) if p.exists()]
    if taken and not force:
        raise FileExistsError(f"{', '.join(map(str, taken))} already exist (use --force to overwrite)")
    if master_path(stem).exists() and not replace_master:
        raise FileExistsError(f"{master_path(stem)} holds the secret K of an image already signed as {stem}; "
                              "add --replace-master to move it aside (it is never deleted)")


def write_master(stem: Path, secret: bytes, root: bytes, force: bool) -> None:
    """The authority's per-image secret, created with mode 600 from the first byte (no world-readable
    moment) in a folder of mode 700, and written BEFORE anything is anchored, so a crash cannot leave a
    signed image without it. With `force` an existing master is renamed, never deleted."""
    path = master_path(stem)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if force and path.exists():
        path.chmod(0o600)
        backup = path.name.removesuffix(".master.json") + f".replaced-{secrets.token_hex(16)}.master.json"
        path.rename(path.with_name(backup))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write(json.dumps({"velum_master": 1, "K": secret.hex(), "root": root.hex()}) + "\n")


def save_level(stem: Path, evidence: Image, sidecar: Sidecar) -> Path | None:
    """Write the level's files; returns the rendition path if the level has a crop or a recipe."""
    ev, sc, pub = paths(stem)
    stem.parent.mkdir(parents=True, exist_ok=True)
    ev.write_bytes(write_png(evidence, sidecar.to_text()))  # one self-contained file...
    sc.write_text(sidecar.to_text(), encoding="ascii")  # ...and the sidecar alone, for channels that strip chunks
    if sidecar.level.crop is None and sidecar.level.recipe is None:
        pub.unlink(missing_ok=True)
        return None
    pub.write_bytes(write_png(render(evidence, sidecar.level.crop, sidecar.level.recipe)))
    return pub


@dataclass(frozen=True)
class _LevelFiles:
    evidence: bytes
    external: bytes | None
    rendition: bytes | None

    @classmethod
    def read(cls, stem: Path, with_rendition: bool = True) -> _LevelFiles:
        ev, sc, pub = paths(stem)
        try:
            with sc.open("rb") as f:
                external = f.read(MAX_SIDECAR + 1)
        except FileNotFoundError:
            external = None
        rendition = pub.read_bytes() if with_rendition and pub.exists() else None
        return cls(ev.read_bytes(), external, rendition)

    def decode(self) -> tuple[Image, Sidecar]:
        text = read_sidecar(self.evidence)
        if text is None:
            if self.external is None or len(self.external) > MAX_SIDECAR:
                raise ValueError("missing or oversized external sidecar")
            text = self.external.decode("ascii")
        return read_png(self.evidence), Sidecar.parse(text)

    def verify(self, trusted: list[Authority], attempts: int = 1, wait: float = 3.0) -> Report:
        for attempt in range(max(1, attempts)):
            if attempt:
                time.sleep(wait)
            report = verify(self.evidence, self.external, trusted, XrplLedger(), self.rendition,
                            max_pixels=config.max_verify_pixels())
            if report.status != UNVERIFIABLE:
                break
        return report


def load_level(stem: Path) -> tuple[Image, Sidecar]:
    """Embedded sidecar first, STEM.velum.json if the PNG has none."""
    return _LevelFiles.read(stem, with_rendition=False).decode()


# ---------------------------------------------------------------- operations (also used by the demo)
def sign_image(original: Image, out: Path, hide: frozenset[int] = frozenset(), force: bool = False,
               replace_master: bool = False) -> tuple[Image, Sidecar, list[str]]:
    """Authority: commit, keep the secret, sign, anchor the manifest, release L0. Returns explorer links."""
    budget = config.max_verify_pixels()
    if original.width * original.height > budget:  # signable, but default verifiers could not check it
        raise ValueError(f"image is {original.width}x{original.height}, above the default verification budget of "
                         f"{budget} pixels: shrink it, or raise VELUM_MAX_VERIFY_PIXELS for signer and verifiers")
    ensure_free(out, force, replace_master)
    authority = config.wallet("AUTHORITY")
    pk, sk = pq.keypair(config.authority_pq_seed())
    secret = secrets.token_bytes(32)
    root = commit(original, secret)
    write_master(out, secret, root, force and replace_master)
    manifest = mf.Manifest(original.width, original.height, root, authority.address)
    sig = mf.sign(manifest, sk)
    m = anchor(authority, mf.MEMO_TYPE, mf.memo_data(manifest, sig))
    d = from_master(manifest, m.hash, hide)
    a = anchor(authority, LEVEL_MEMO, d.memo_data())
    evidence, sidecar = release_master(original, secret, manifest, sig, pk, m.hash, d, a.hash)
    save_level(out, evidence, sidecar)
    return evidence, sidecar, [m.explorer_url, a.explorer_url]


def derive(source: tuple[Image, Sidecar], role: str, out: Path, hide: frozenset[int] = frozenset(),
           crop: tuple[int, int, int, int] | None = None, recipe: Recipe | None = None,
           force: bool = False) -> tuple[Image, Sidecar, str]:
    """Producer `role`: a more redacted copy of a loaded level, anchored by that role's account."""
    ensure_free(out, force)
    producer = config.wallet(role)
    ev, sc = source
    d = from_level(sc, producer.address, hide, crop, recipe)
    output_size(ev.width, ev.height, crop, recipe)
    a = anchor(producer, LEVEL_MEMO, d.memo_data())
    evidence, sidecar = release_level(ev, sc, d, a.hash)
    save_level(out, evidence, sidecar)
    return evidence, sidecar, a.explorer_url


def verify_files(stem: Path, trust_file: Path, with_rendition: bool = True) -> Report:
    files = _LevelFiles.read(stem, with_rendition)
    return files.verify(parse_trust_list(trust_file.read_text()))


def verify_settled(stem: Path, trust_file: Path, attempts: int = 4, wait: float = 3.0) -> Report:
    """Retry inconclusive checks of the same files while an anchor propagates."""
    return _LevelFiles.read(stem).verify(parse_trust_list(trust_file.read_text()), attempts, wait)


def verified_source(stem: Path, trust_file: Path) -> tuple[Image, Sidecar]:
    """Verify and decode the same bytes even if the files change during a ledger lookup."""
    files = _LevelFiles.read(stem)
    report = files.verify(parse_trust_list(trust_file.read_text()), attempts=4)
    if report.status != ACCEPT:
        raise ValueError(f"source level {stem} does not verify ({report.status}): refusing to anchor a copy of it"
                         f"\n{report_text(report)}")
    return files.decode()


# ---------------------------------------------------------------- argument parsing
def tile_set(grid: Grid, singles: str | None, rects: list[str]) -> frozenset[int]:
    """--hide 5,6,7 and --hide-rect col0:row0:col1:row1 (inclusive) -> tile indices. Anything outside the
    grid is an error: silently wrapping a column into the next row would black out the wrong place."""
    out = set()
    for value in (singles.split(",") if singles else []):
        i = int(value)
        if not 0 <= i < grid.n:
            raise ValueError(f"tile {i} outside 0..{grid.n - 1}")
        out.add(i)
    for rect in rects:
        c0, r0, c1, r1 = _ints(rect, ":", 4)
        if not (0 <= c0 <= c1 < grid.cols and 0 <= r0 <= r1 < grid.rows):
            raise ValueError(f"--hide-rect {rect}: columns must be 0..{grid.cols - 1}, rows 0..{grid.rows - 1}, "
                             "start <= end")
        out |= {r * grid.cols + c for r in range(r0, r1 + 1) for c in range(c0, c1 + 1)}
    return frozenset(out)


class BadNumbers(argparse.ArgumentTypeError, ValueError):
    """Shown by argparse as a usage error, and caught by main() like any other bad input."""


def _ints(text: str, sep: str, count: int) -> tuple[int, ...]:
    try:
        values = tuple(int(v) for v in text.split(sep))
    except ValueError:
        values = ()
    if len(values) != count:
        raise BadNumbers(f"{text!r}: expected {count} integers separated by {sep!r}")
    return values


def report_text(report: Report) -> str:
    lines = report.lines()
    for key in ("sidecar", "sidecar_note", "authority", "signed_at", "published_by", "published_at", "hidden_percent"):
        if key in report.facts:
            lines.append(f"  {key}: {report.facts[key]}")
    if "mask" in report.facts:
        lines.append("  mask (# hidden):")
        lines += [f"    {row}" for row in report.facts["mask"]]  # type: ignore[attr-defined]
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="velum", description="Verifiable redaction of signed images on XRPL.")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sign", help="authority: sign an image, anchor it, release L0")
    s.add_argument("image", type=Path)
    s.add_argument("--out", type=Path, required=True, help="output directory")
    s.add_argument("--name", default="l0")
    s.add_argument("--force", action="store_true", help="overwrite existing level files")
    s.add_argument("--replace-master", action="store_true",
                   help="with --force: also replace this stem's secret K (the old one is moved aside, never deleted)")

    d = sub.add_parser("derive", help="producer: make and anchor a more redacted copy")
    d.add_argument("source", type=Path, help="stem of the source level")
    d.add_argument("--as", dest="role", required=True, choices=config.ROLES)
    d.add_argument("--name", required=True, help="stem of the new level, next to the source")
    d.add_argument("--hide", help="tile indices, e.g. 6,7,8")
    d.add_argument("--hide-rect", action="append", default=[], help="col0:row0:col1:row1, inclusive")
    d.add_argument("--crop", type=lambda t: _ints(t, ":", 4), help="col0:row0:cols:rows")
    d.add_argument("--rotate", type=int, default=0, choices=(0, 90, 180, 270))
    d.add_argument("--resize", type=lambda t: _ints(t, "x", 2), help="WxH, shrink only")
    d.add_argument("--brightness", type=int, default=0)
    d.add_argument("--contrast", type=int, default=0)
    d.add_argument("--force", action="store_true", help="overwrite an existing level")
    d.add_argument("--trust", type=Path, default=config.ROOT / "trust.local.json",
                   help="trust list used to verify the source before deriving")

    v = sub.add_parser("verify", help="anyone: verify a level against the ledger")
    v.add_argument("stem", type=Path)
    v.add_argument("--trust", type=Path, default=config.ROOT / "trust.local.json")
    v.add_argument("--no-rendition", action="store_true")
    return p


def run(a: argparse.Namespace) -> int:
    if a.cmd == "sign":
        stem = a.out / check_name(a.name)
        _, _, links = sign_image(read_png(a.image.read_bytes()), stem, force=a.force,
                                 replace_master=a.replace_master)
        print(f"signed {a.image} -> {stem}.png / .velum.json (secret: {master_path(stem)})")
        print("\n".join(f"  {link}" for link in links))
        return 0
    if a.cmd == "derive":
        stem = a.source.parent / check_name(a.name)
        if stem.resolve() == a.source.resolve():
            raise ValueError("--name must differ from the source level")
        source = verified_source(a.source, a.trust)
        grid = Grid(source[1].manifest.width, source[1].manifest.height)
        recipe = None
        if a.rotate or a.resize or a.brightness or a.contrast:
            recipe = Recipe(a.rotate, a.resize, a.brightness, a.contrast)
        _, _, link = derive(source, a.role, stem, tile_set(grid, a.hide, a.hide_rect), a.crop, recipe, a.force)
        print(f"{a.role} derived {stem} from {a.source}\n  {link}")
        return 0
    report = verify_files(a.stem, a.trust, not a.no_rendition)
    print(report_text(report))
    return {ACCEPT: EXIT_ACCEPT, REJECT: EXIT_REJECT}.get(report.status, EXIT_UNVERIFIABLE)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)  # usage errors exit with 2 here
    try:
        return run(args)
    except (ValueError, RuntimeError, OSError) as exc:  # bad input, missing wallet, failed tx, missing file
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
