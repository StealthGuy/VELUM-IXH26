"""The verifier: checks V1-V6 of docs/VELUM.md section 7.

Every check runs and is reported. Outcome:
    ACCEPT        every check passed
    REJECT        at least one check failed for a reason that is not the network
    UNVERIFIABLE  the only failures are inconclusive (ledger unreachable, image above this verifier's
                  pixel budget): they say nothing about authenticity, never "verified" and never "forged"
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import merkle, pq
from .canonical import CanonicalError
from .descriptor import MEMO_TYPE as LEVEL_MEMO
from .image import MAX_PIXELS, Image
from .ledger import LedgerTx, LedgerUnavailable, LedgerView, TxNotFound, anchor_problem
from .level import outside_crop
from .manifest import MEMO_TYPE as MANIFEST_MEMO
from .manifest import memo_data, signature_ok
from .png import MAX_SIDECAR, OverBudget, PngError, SidecarError, read_png, read_sidecar
from .recipe import output_size, render
from .schema import SchemaError
from .sidecar import Sidecar
from .tiles import Grid, leaf_hash, tile_bytes
from .trust import Authority

ACCEPT, REJECT, UNVERIFIABLE = "ACCEPT", "REJECT", "UNVERIFIABLE"
# Verifier policy, not a format limit (docs/VELUM.md section 3): pure-Python decoding costs CPU per pixel,
# and a few kilobytes of PNG can declare millions of pixels. 2^23 = 8.4 MP covers 4K UHD.
VERIFY_PIXELS = 1 << 23
TITLES = {
    "V1": "authority signature",
    "V2": "authority anchor",
    "V3": "pixels match the signed root",
    "V4": "level anchor",
    "V5": "redaction rules",
    "V6": "rendition",
}


@dataclass(frozen=True)
class Check:
    id: str
    ok: bool
    detail: str
    inconclusive: bool = False  # failed without saying anything about authenticity (network, budget)


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    facts: dict[str, object] = field(default_factory=dict)

    @property
    def status(self) -> str:
        failed = [c for c in self.checks if not c.ok]
        if not failed:
            return ACCEPT
        return UNVERIFIABLE if all(c.inconclusive for c in failed) else REJECT

    def lines(self) -> list[str]:
        out = [f"[{'OK' if c.ok else 'NO'}] {c.id} {TITLES[c.id]}: {c.detail}" for c in self.checks]
        return out + [f"VELUM verdict: {self.status}"]


class _Ledger:
    """Caches lookups so a transaction is fetched once per verification."""

    def __init__(self, view: LedgerView) -> None:
        self.view = view
        self.cache: dict[str, LedgerTx] = {}

    def get(self, tx_hash: str) -> LedgerTx:
        if tx_hash not in self.cache:
            self.cache[tx_hash] = self.view.transaction(tx_hash)
        return self.cache[tx_hash]


def _run(check_id: str, fn: Callable[[], str]) -> Check:
    """Run one check: its function returns a success detail or raises with the failure reason."""
    try:
        return Check(check_id, True, fn())
    except LedgerUnavailable as exc:
        return Check(check_id, False, f"could not reach the ledger: {exc}", inconclusive=True)
    except OverBudget as exc:  # an authentic large image must not be called forged by a small verifier
        return Check(check_id, False, f"{exc}; raise VELUM_MAX_VERIFY_PIXELS to check it", inconclusive=True)
    except TxNotFound as exc:
        return Check(check_id, False, f"transaction not found: {exc}")
    except ValueError as exc:
        return Check(check_id, False, str(exc))
    except Exception as exc:  # fail closed: any unexpected error is a failed check, never a crash or a pass
        return Check(check_id, False, f"internal error: {type(exc).__name__}: {exc}")


def _iso(t: int) -> str:
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _external_text(sidecar: str | bytes | None) -> str | None:
    """An external sidecar file as text; bytes that are not ASCII cannot be a sidecar."""
    if sidecar is not None and len(sidecar) > MAX_SIDECAR:
        raise SchemaError(f"external sidecar exceeds {MAX_SIDECAR} bytes")
    if isinstance(sidecar, bytes):
        try:
            return sidecar.decode("ascii")
        except UnicodeDecodeError as exc:
            raise SchemaError("the external sidecar file is not ASCII") from exc
    return sidecar


def verify(evidence_png: bytes, sidecar_text: str | bytes | None, trusted: Sequence[Authority], view: LedgerView,
           rendition_png: bytes | None = None, max_pixels: int = VERIFY_PIXELS) -> Report:
    """The sidecar embedded in the evidence PNG wins; `sidecar_text` (an external file) is used only when
    the PNG carries none, or is not a readable PNG at all. A broken embedded sidecar is a failure, never a
    reason to use the external file. Either way the sidecar is fully checked: where it came from does
    not make it trusted. `max_pixels` is this verifier's budget for the evidence and the rendition."""
    report = Report()
    max_pixels = min(max_pixels, MAX_PIXELS)
    try:
        try:
            embedded = read_sidecar(evidence_png)
        except SidecarError:
            raise  # two chunks, bad compression, not ASCII...: an error, not "no sidecar"
        except PngError as exc:  # unreadable evidence: V3 will report it; an external sidecar may still parse
            if sidecar_text is None:
                raise SchemaError(f"no sidecar: the evidence PNG is unreadable ({exc}) and no external file given")
            embedded = None
        external = _external_text(sidecar_text) if embedded is None else None
        text = embedded if embedded is not None else external
        if text is None:
            raise SchemaError("no sidecar: none embedded in the PNG and no external file given")
        report.facts["sidecar"] = "embedded in the PNG" if embedded is not None else "external file"
        if embedded is not None and sidecar_text is not None and sidecar_text not in (embedded, embedded.encode()):
            report.facts["sidecar_note"] = "the external sidecar file differs from the embedded one and was ignored"
        sc = Sidecar.parse(text)
    except Exception as exc:  # fail closed: hostile input is a failed check, never a crash
        reason = str(exc) if isinstance(exc, (CanonicalError, SchemaError, PngError)) else \
            f"{type(exc).__name__}: {exc}"
        report.checks.append(Check("V1", False, f"invalid sidecar: {reason}"))
        report.checks += [Check(k, False, "not run: invalid sidecar") for k in ("V2", "V3", "V4", "V5", "V6")]
        return report

    ledger = _Ledger(view)
    grid = Grid(sc.manifest.width, sc.manifest.height)
    authority = next((a for a in trusted if a.xrpl_address == sc.manifest.authority and a.network == view.network
                      and a.pk_sha256 == hashlib.sha256(sc.authority_pk).digest()), None)

    def v1() -> str:
        if authority is None:
            raise ValueError(f"authority address and ML-DSA key are not in the trust list for {view.network}")
        if not signature_ok(sc.manifest, sc.authority_pk, sc.manifest_sig):
            raise ValueError("ML-DSA-44 signature on the manifest is invalid")
        report.facts["authority"] = authority.name
        return f"{authority.name} ({sc.manifest.authority}), key {pq.fingerprint(sc.authority_pk)[:16]}…"

    def v2() -> str:
        tx = ledger.get(sc.manifest_tx)
        problem = anchor_problem(tx, sc.manifest.authority, MANIFEST_MEMO, memo_data(sc.manifest, sc.manifest_sig))
        if problem:
            raise ValueError(f"manifest anchor {sc.manifest_tx[:12]}…: {problem}")
        if authority is not None and not authority.accepts_time(tx.close_time):
            raise ValueError(f"signed at {_iso(tx.close_time)}, after the authority's not_after")
        report.facts["signed_at"] = _iso(tx.close_time)
        return f"anchored in ledger {tx.ledger_index} at {_iso(tx.close_time)}"

    evidence: Image | None = None
    evidence_over_budget = False

    def v3() -> str:
        nonlocal evidence, evidence_over_budget
        try:
            img = read_png(evidence_png, strict=True, max_pixels=max_pixels)
        except OverBudget:
            evidence_over_budget = True
            raise
        if (img.width, img.height) != (sc.manifest.width, sc.manifest.height):
            raise ValueError(f"evidence is {img.width}x{img.height}, manifest says "
                             f"{sc.manifest.width}x{sc.manifest.height}")
        evidence = img
        leaves = []
        for i in range(grid.n):
            if i in sc.hidden:
                x0, y0, w, h = grid.rect(i)
                if any(img.rgb[(y * img.width + x0) * 3:(y * img.width + x0 + w) * 3].count(0) != w * 3
                       for y in range(y0, y0 + h)):
                    raise ValueError(f"hidden tile {i} is not black in the evidence image")
                leaves.append(sc.hidden[i])
            else:
                leaves.append(leaf_hash(i, sc.visible[i], tile_bytes(img, i)))
        if merkle.root(leaves) != sc.manifest.root:
            raise ValueError("visible tiles and hidden leaf hashes do not rebuild the signed root")
        return f"{len(sc.visible)} visible and {len(sc.hidden)} hidden tiles rebuild the root"

    def v4() -> str:
        d = sc.level
        if d.manifest_tx != sc.manifest_tx:
            raise ValueError("the level points to another manifest anchor")
        tx = ledger.get(sc.level_tx)
        problem = anchor_problem(tx, d.producer, LEVEL_MEMO, d.memo_data())
        if problem:
            raise ValueError(f"level anchor {sc.level_tx[:12]}…: {problem}")
        if tx.ledger_index < ledger.get(sc.manifest_tx).ledger_index:
            raise ValueError("the level is anchored before the manifest")
        report.facts["published_by"] = d.producer
        report.facts["published_at"] = _iso(tx.close_time)
        return f"published by {d.producer} in ledger {tx.ledger_index} at {_iso(tx.close_time)}"

    def v5() -> str:
        d = sc.level
        if not outside_crop(grid, d.crop) <= d.hidden:
            raise ValueError("tiles outside the crop are not hidden")
        output_size(grid.width, grid.height, d.crop, d.recipe)  # crop and recipe can be applied
        if set(sc.hidden) != d.hidden:
            raise ValueError("the sidecar's hidden tiles differ from the level's bitmap")
        hidden_px = sum(grid.rect(i)[2] * grid.rect(i)[3] for i in sc.hidden)
        report.facts["hidden_percent"] = round(100 * hidden_px / (grid.width * grid.height), 1)
        report.facts["mask"] = ["".join("#" if r * grid.cols + c in sc.hidden else "." for c in range(grid.cols))
                                for r in range(grid.rows)]
        return f"{len(sc.hidden)}/{grid.n} tiles hidden, crop and recipe valid"

    def v6() -> str:
        if rendition_png is None:
            return "no rendition given"
        got = read_png(rendition_png, strict=True, max_pixels=max_pixels)
        if evidence_over_budget:
            size = output_size(grid.width, grid.height, sc.level.crop, sc.level.recipe)
            if (got.width, got.height) != size:
                raise ValueError("rendition dimensions differ from the recipe")
            raise OverBudget("rendition comparison needs the over-budget evidence image")
        if evidence is None:
            raise ValueError("evidence image unusable (see V3)")
        expected = render(evidence, sc.level.crop, sc.level.recipe)
        if got != expected:
            raise ValueError(f"rendition pixels differ from the recipe applied to the evidence "
                             f"({got.width}x{got.height} vs {expected.width}x{expected.height})")
        return f"{got.width}x{got.height} rendition equals the recipe applied to the evidence"

    for check_id, fn in (("V1", v1), ("V2", v2), ("V3", v3), ("V4", v4), ("V5", v5), ("V6", v6)):
        report.checks.append(_run(check_id, fn))
    return report
