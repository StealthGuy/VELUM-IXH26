"""Live proof of build step 2 on XRPL Testnet: anchors, then verification against the real ledger.

    make prove

1. AUTHORITY signs a 320 x 192 synthetic image (ML-DSA-44) and anchors the manifest
2. AUTHORITY releases L0 (full image) and anchors it
3. LAB makes a more redacted copy (3 of the 5 x 3 tiles black) and anchors it
4. both copies are verified from the PNG alone (embedded sidecar) against a quorum of Testnet nodes;
   a flipped pixel must be REJECTED
Writes out/prove/ (evidence PNGs with the sidecar embedded, plus the sidecar as a separate fallback file,
usable as live samples) and prints Explorer links.
The salt secret K is random and not kept: this proves the anchoring, it is not a real release.
Exit code != 0 if any expectation fails.
"""
from __future__ import annotations

import secrets
import sys

from velum import config, pq
from velum import manifest as mf
from velum.descriptor import MEMO_TYPE as LEVEL_MEMO
from velum.image import Image
from velum.level import commit, from_level, from_master, release_level, release_master
from velum.png import write_png
from velum.trust import parse_trust_list
from velum.verify import ACCEPT, REJECT, verify
from velum.xrpl_ledger import SubmitError, XrplLedger, anchor

OUT = config.ROOT / "out" / "prove"


def synthetic(width: int, height: int) -> Image:
    return Image(width, height, bytes(((x * 3 + y * 5 + c * 70) ^ (x // 16 * y // 16)) & 0xFF
                                      for y in range(height) for x in range(width) for c in range(3)))


def main() -> int:
    authority, lab = config.wallet("AUTHORITY"), config.wallet("LAB")
    pk, sk = pq.keypair(config.authority_pq_seed())
    trust = parse_trust_list((config.ROOT / "trust.local.json").read_text())
    ledger = XrplLedger()
    print(f"network {ledger.network} | authority {authority.address} | lab {lab.address}")
    OUT.mkdir(parents=True, exist_ok=True)

    try:
        original, secret = synthetic(320, 192), secrets.token_bytes(32)
        manifest = mf.Manifest(original.width, original.height, commit(original, secret), authority.address)
        sig = mf.sign(manifest, sk)
        m = anchor(authority, mf.MEMO_TYPE, mf.memo_data(manifest, sig))
        print(f"[1] manifest anchored   {m.explorer_url}")

        d0 = from_master(manifest, m.hash)
        a0 = anchor(authority, LEVEL_MEMO, d0.memo_data())
        ev0, sc0 = release_master(original, secret, manifest, sig, pk, m.hash, d0, a0.hash)
        print(f"[2] L0 anchored         {a0.explorer_url}")

        d1 = from_level(sc0, lab.address, hide=frozenset({6, 7, 8}))
        a1 = anchor(lab, LEVEL_MEMO, d1.memo_data())
        ev1, sc1 = release_level(ev0, sc0, d1, a1.hash)
        print(f"[3] LAB copy anchored   {a1.explorer_url}")
    except SubmitError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1

    for name, ev, sc in (("L0", ev0, sc0), ("L1", ev1, sc1)):
        (OUT / f"{name}.png").write_bytes(write_png(ev, sc.to_text()))  # one self-contained file...
        (OUT / f"{name}.velum.json").write_text(sc.to_text(), encoding="ascii")  # ...and the fallback

    print("\n[4] verification against the live ledger")
    results = []
    for name, ev, sc, want in (("L0", ev0, sc0, ACCEPT), ("L1 (LAB)", ev1, sc1, ACCEPT)):
        report = verify(write_png(ev, sc.to_text()), None, trust, ledger)
        results.append(report.status == want)
        print(f"\n  {name}: {report.status}")
        print("\n".join(f"    {line}" for line in report.lines()[:-1]))
    rgb = bytearray(ev1.rgb)
    rgb[0] ^= 1
    report = verify(write_png(Image(ev1.width, ev1.height, bytes(rgb)), sc1.to_text()), None, trust, ledger)
    results.append(report.status == REJECT)
    print(f"\n  L1 with one flipped pixel: {report.status} "
          f"(failed: {', '.join(c.id for c in report.checks if not c.ok)})")
    print(f"\nwrote {OUT.relative_to(config.ROOT)}/")
    if not all(results):
        print("UNEXPECTED RESULT", file=sys.stderr)
        return 1
    print("ALL EXPECTATIONS MET")
    return 0


if __name__ == "__main__":
    sys.exit(main())
