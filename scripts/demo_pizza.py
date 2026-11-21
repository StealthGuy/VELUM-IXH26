"""THE CASE OF THE MISSING PIZZA: the VELUM demo, live on XRPL Testnet.

    make demo

Exhibit A (samples/missing_pizza_case.png, 1280 x 720, 20 x 12 tiles of 64 px):
    the suspect's face   tiles cols 6-8 x rows 0-3, plus the ear at col 9 rows 1-2
    "Secret Passwd: 4"   tiles cols 8-10 x rows 9-10

AUTHORITY ("Department of Hackathon Integrity") signs it      -> l0, for the judges
LAB hides the password                                        -> l1, for analysts
NEWSROOM hides the suspect, shrinks and brightens it          -> l2 + l2.public.png, for everyone
Each producer verifies its source before deriving; everything is verified against the live ledger
(a quorum of Testnet nodes), then three forgeries must be REJECTED. The forgeries carry their sidecar
embedded in the PNG, the way real files travel. Files go to out/demo/; the authority's secret K goes to
the private master folder (~/.velum/masters or VELUM_MASTER_DIR), never next to them.
"""
from __future__ import annotations

import sys
from dataclasses import replace

from velum import config, pq
from velum import manifest as mf
from velum.cli import derive, report_text, sign_image, tile_set, verified_source, verify_files, verify_settled
from velum.descriptor import Recipe
from velum.image import Image
from velum.png import read_png, read_sidecar, write_png
from velum.sidecar import Sidecar
from velum.tiles import Grid
from velum.trust import parse_trust_list
from velum.verify import ACCEPT, REJECT, Report, verify
from velum.xrpl_ledger import SubmitError, XrplLedger

EXHIBIT = config.ROOT / "samples" / "missing_pizza_case.png"
OUT = config.ROOT / "out" / "demo"
TRUST = config.ROOT / "trust.local.json"

# figlet "small" font (generated once with pyfiglet, pasted here: no dependency)
MORAL = r"""
__   __                         _    _    _
\ \ / /__ _  _   __ __ _ _ _   | |_ (_)__| |___
 \ V / _ \ || | / _/ _` | ' \  | ' \| / _` / -_)
  |_|\___/\_,_| \__\__,_|_||_| |_||_|_\__,_\___|

 _   _          _            _   _
| |_| |_  ___  | |_ _ _ _  _| |_| |_
|  _| ' \/ -_) |  _| '_| || |  _| ' \ _
 \__|_||_\___|  \__|_|  \_,_|\__|_||_(_)

__   __                       _ _      __      _         _ _
\ \ / /__ _  _   __ __ _ _ _ ( ) |_   / _|__ _| |_____  (_) |_
 \ V / _ \ || | / _/ _` | ' \|/|  _| |  _/ _` | / / -_) | |  _|_
  |_|\___/\_,_| \__\__,_|_||_|  \__| |_| \__,_|_\_\___| |_|\__(_)
"""


def say(text: str) -> None:
    print(f"\n{text}")


def expect(label: str, report: Report, status: str, failed: list[str], results: list[bool]) -> None:
    got = [c.id for c in report.checks if not c.ok]
    ok = report.status == status and got == failed
    results.append(ok)
    print(f"  {label}: {report.status}{' (failed: ' + ', '.join(got) + ')' if got else ''}"
          f"{'' if ok else '   <-- UNEXPECTED'}")


def paint(img: Image, x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]) -> Image:
    rgb = bytearray(img.rgb)
    for y in range(y0, y1):
        for x in range(x0, x1):
            i = (y * img.width + x) * 3
            rgb[i:i + 3] = bytes(color)
    return Image(img.width, img.height, bytes(rgb))


def main() -> int:
    original = read_png(EXHIBIT.read_bytes())
    grid = Grid(original.width, original.height)
    password = tile_set(grid, None, ["8:9:10:10"])
    suspect = tile_set(grid, "29,49", ["6:0:8:3"])
    print("THE CASE OF THE MISSING PIZZA")
    print(f"Exhibit A: {EXHIBIT.name}, {original.width}x{original.height}, {grid.cols}x{grid.rows} tiles. "
          f"Network: {config.network()}.")

    try:
        say("[1] The Department of Hackathon Integrity signs Exhibit A (ML-DSA-44) and anchors it on XRPL.")
        # the demo rebuilds out/demo each run; the previous run's master is moved aside, never deleted
        _, _, links = sign_image(original, OUT / "l0", force=True, replace_master=True)
        print(f"    manifest anchored: {links[0]}\n    L0 anchored:       {links[1]}")
        print("    'Exhibit A. Unredacted. Judges only.'")

        say("[2] LAB: 'Security first: the Wi-Fi password is classified.'")
        _, _, link = derive(verified_source(OUT / "l0", TRUST), "LAB", OUT / "l1", hide=password, force=True)
        print(f"    {len(password)} tiles blacked out, anchored by LAB: {link}")

        say("[3] NEWSROOM: 'Suspect's identity protected. Pizza: still gone.'")
        _, _, link = derive(verified_source(OUT / "l1", TRUST), "NEWSROOM", OUT / "l2", hide=suspect,
                            recipe=Recipe(resize=(640, 360), brightness=8, contrast=12), force=True)
        print(f"    {len(suspect)} more tiles blacked out, shrunk to 640x360, anchored by NEWSROOM: {link}")
    except SubmitError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1

    results: list[bool] = []
    say("[4] Anyone verifies, reading only the files and the public ledger:")
    for label, stem in (("L0 for the judges  ", "l0"), ("L1 for analysts    ", "l1"), ("L2 for the public  ", "l2")):
        expect(label, verify_settled(OUT / stem, TRUST), ACCEPT, [], results)  # l2 was anchored seconds ago
    print("\n" + report_text(verify_files(OUT / "l2", TRUST)))

    say("[5] Forgeries, checked against the same ledger:")
    trust, ledger = parse_trust_list(TRUST.read_text()), XrplLedger()
    l2_png = (OUT / "l2.png").read_bytes()
    evidence, sidecar_text = read_png(l2_png), read_sidecar(l2_png)  # the sidecar travels inside the PNG
    if sidecar_text is None:
        print("FAILED: l2.png carries no embedded sidecar", file=sys.stderr)
        return 1
    public = read_png((OUT / "l2.public.png").read_bytes())

    restored = paint(public, 20, 280, 200, 350, (225, 140, 40))  # a pizza appears in the empty box
    (OUT / "attack_pizza_restored.public.png").write_bytes(write_png(restored))
    expect("'Pizza restored' in the public image", verify(l2_png, None, trust, ledger, write_png(restored)),
           REJECT, ["V6"], results)

    unmasked = bytearray(evidence.rgb)  # the original face pasted back over the black tiles
    for i in suspect:
        x0, y0, w, h = grid.rect(i)
        for y in range(y0, y0 + h):
            s = (y * original.width + x0) * 3
            unmasked[s:s + w * 3] = original.rgb[s:s + w * 3]
    unmasked_png = write_png(Image(evidence.width, evidence.height, bytes(unmasked)), sidecar_text)
    (OUT / "attack_suspect_unmasked.png").write_bytes(unmasked_png)
    expect("'Suspect unmasked' in the evidence    ", verify(unmasked_png, None, trust, ledger),
           REJECT, ["V3"], results)

    sc = Sidecar.parse(sidecar_text)  # the forger re-signs the manifest with a key of their own
    fake_pk, fake_sk = pq.keypair(bytes([66]) * 32)
    forged = replace(sc, authority_pk=fake_pk, manifest_sig=mf.sign(sc.manifest, fake_sk)).to_text()
    expect("'Fake authority' signature            ", verify(write_png(evidence, forged), None, trust, ledger),
           REJECT, ["V1", "V2"], results)  # V2: the anchored memo holds the hash of the real signature

    print(f"\nFiles: {OUT.relative_to(config.ROOT)}/")
    if not all(results):
        print("UNEXPECTED RESULT", file=sys.stderr)
        return 1
    print(MORAL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
