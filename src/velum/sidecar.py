"""The sidecar (docs/VELUM.md section 6.2), with strict parsing. It travels embedded in the evidence PNG
(zTXt chunk "velum.sidecar"); NAME.velum.json holds the same text, used only when the PNG carries none.

Hidden tiles carry only their leaf hash. The schema has no place for a hidden tile's salt, and every
tile index must appear exactly once across `visible` and `hidden`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from . import pq, schema
from .canonical import loads_strict
from .descriptor import Descriptor
from .manifest import Manifest
from .tiles import SALT_BYTES, Grid

VERSION = 1
_KEYS = {"velum", "manifest", "manifest_sig", "authority_pk", "manifest_tx", "level", "level_tx", "visible", "hidden"}


@dataclass(frozen=True)
class Sidecar:
    manifest: Manifest
    manifest_sig: bytes
    authority_pk: bytes
    manifest_tx: str
    level: Descriptor  # this copy's redaction, crop and recipe
    level_tx: str  # the transaction that anchored `level`
    visible: dict[int, bytes]  # tile index -> salt
    hidden: dict[int, bytes]  # tile index -> leaf hash

    def to_text(self) -> str:
        """The file content. Not hashed anywhere, so it is merely pretty, sorted JSON."""
        value = {
            "velum": VERSION,
            "manifest": self.manifest.to_json(),
            "manifest_sig": self.manifest_sig.hex(),
            "authority_pk": self.authority_pk.hex(),
            "manifest_tx": self.manifest_tx,
            "level": self.level.to_json(),
            "level_tx": self.level_tx,
            "visible": [[i, self.visible[i].hex()] for i in sorted(self.visible)],
            "hidden": [[i, self.hidden[i].hex()] for i in sorted(self.hidden)],
        }
        return json.dumps(value, indent=1, sort_keys=True) + "\n"

    @classmethod
    def parse(cls, content: str) -> Sidecar:
        """Strict: raises CanonicalError or SchemaError on anything unexpected."""
        s = schema.obj(loads_strict(content), _KEYS, "sidecar")
        schema.integer(s["velum"], "sidecar.velum", VERSION, VERSION)
        manifest = Manifest.from_json(s["manifest"])
        n = Grid(manifest.width, manifest.height).n
        visible = _tile_map(s["visible"], SALT_BYTES, n, "sidecar.visible")
        hidden = _tile_map(s["hidden"], 32, n, "sidecar.hidden")
        if set(visible) & set(hidden) or len(visible) + len(hidden) != n:
            raise schema.SchemaError("sidecar: every tile must be listed exactly once, as visible or hidden")
        return cls(manifest=manifest,
                   manifest_sig=schema.hex_bytes(s["manifest_sig"], pq.SIG_BYTES, "sidecar.manifest_sig"),
                   authority_pk=schema.hex_bytes(s["authority_pk"], pq.PK_BYTES, "sidecar.authority_pk"),
                   manifest_tx=schema.tx_hash(s["manifest_tx"], "sidecar.manifest_tx"),
                   level=Descriptor.from_json(s["level"], n, "sidecar.level"),
                   level_tx=schema.tx_hash(s["level_tx"], "sidecar.level_tx"),
                   visible=visible, hidden=hidden)


def _tile_map(value: object, length: int, n: int, where: str) -> dict[int, bytes]:
    """[[index, hex], ...] sorted by strictly increasing index -> {index: bytes}."""
    out: dict[int, bytes] = {}
    last = -1
    for k, item in enumerate(schema.array(value, where)):
        pair = schema.array(item, f"{where}[{k}]")
        if len(pair) != 2:
            raise schema.SchemaError(f"{where}[{k}]: expected [index, hex]")
        i = schema.integer(pair[0], f"{where}[{k}][0]", 0, n - 1)
        if i <= last:
            raise schema.SchemaError(f"{where}: indices must be strictly increasing")
        out[i] = schema.hex_bytes(pair[1], length, f"{where}[{k}][1]")
        last = i
    return out
