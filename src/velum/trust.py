"""The verifier's trust list: which authorities count, pinned out of band (docs/VELUM.md section 2).

    [{"name": "...", "network": "testnet", "xrpl_address": "r...",
      "mldsa44_pk_sha256": "<64 lowercase hex>", "not_after": "2027-12-31T23:59:59Z" | null}]
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from . import schema
from .canonical import loads_strict

_KEYS = {"name", "network", "xrpl_address", "mldsa44_pk_sha256", "not_after"}
_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_TIME_SHAPE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")  # strptime alone accepts 2027-1-1T1:1:1Z


@dataclass(frozen=True)
class Authority:
    name: str
    network: str
    xrpl_address: str
    pk_sha256: bytes
    not_after: int | None  # Unix seconds; manifests signed at or after this time are refused

    def accepts_time(self, t: int) -> bool:
        return self.not_after is None or t < self.not_after


def parse_trust_list(content: str) -> list[Authority]:
    out = []
    for k, item in enumerate(schema.array(loads_strict(content), "trust")):
        e = schema.obj(item, _KEYS, f"trust[{k}]")
        not_after = None
        if e["not_after"] is not None:
            when = schema.text(e["not_after"], f"trust[{k}].not_after")
            try:
                if not _TIME_SHAPE.fullmatch(when):
                    raise ValueError(when)
                not_after = int(datetime.strptime(when, _TIME_FORMAT).replace(tzinfo=timezone.utc).timestamp())
            except ValueError as exc:
                raise schema.SchemaError(f"trust[{k}].not_after: expected YYYY-MM-DDTHH:MM:SSZ") from exc
        out.append(Authority(name=schema.text(e["name"], f"trust[{k}].name"),
                             network=schema.text(e["network"], f"trust[{k}].network"),
                             xrpl_address=schema.address(e["xrpl_address"], f"trust[{k}].xrpl_address"),
                             pk_sha256=schema.hex_bytes(e["mldsa44_pk_sha256"], 32, f"trust[{k}].mldsa44_pk_sha256"),
                             not_after=not_after))
        a = out[-1]
        if any((b.network, b.xrpl_address, b.pk_sha256) == (a.network, a.xrpl_address, a.pk_sha256) for b in out[:-1]):
            # two not_after values for one key: revocation would depend on the order of the entries
            raise schema.SchemaError(f"trust[{k}]: duplicate entry for {a.xrpl_address} and this key on {a.network}")
    return out
