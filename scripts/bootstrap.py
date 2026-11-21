"""Create the demo wallets ONCE. The only caller of the XRPL faucet (AGENTS.md rule 4).

    make bootstrap

Idempotent: roles that already have a seed in .env.local are skipped, so the faucet is called only for
missing ones. Writes, without ever printing a secret:
    .env.local         VELUM_SEED_<ROLE> for AUTHORITY, LAB, NEWSROOM; VELUM_AUTHORITY_PQ_SEED (chmod 600)
    trust.local.json   a trust list with the demo authority (public data; gitignored, it is per machine)
"""
from __future__ import annotations

import json
import os
import secrets
import sys

from xrpl.wallet import generate_faucet_wallet

from velum import config, pq

ENV_LOCAL = config.ROOT / ".env.local"
TRUST_LOCAL = config.ROOT / "trust.local.json"


def append_secret(key: str, value: str) -> None:
    fd = os.open(ENV_LOCAL, os.O_APPEND | os.O_WRONLY | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        os.fchmod(f.fileno(), 0o600)
        f.write(f"{key}={value}\n")
    os.environ[key] = value


def main() -> int:
    if config.network() != "testnet":
        print("bootstrap only funds Testnet wallets", file=sys.stderr)
        return 2
    config.load_env()
    for role in config.ROLES:
        key = f"VELUM_SEED_{role}"
        if os.environ.get(key):
            print(f"= {role:<9} {config.wallet(role).address} (already in .env.local)")
            continue
        wallet = generate_faucet_wallet(config.client())  # funded by the Testnet faucet
        append_secret(key, str(wallet.seed))
        print(f"+ {role:<9} {wallet.address} funded by the faucet")

    if not os.environ.get("VELUM_AUTHORITY_PQ_SEED"):
        append_secret("VELUM_AUTHORITY_PQ_SEED", secrets.token_hex(32))
        print("+ authority ML-DSA-44 seed created")
    pk, _ = pq.keypair(config.authority_pq_seed())

    entry = {"name": "VELUM Demo Authority", "network": config.network(),
             "xrpl_address": config.wallet("AUTHORITY").address,
             "mldsa44_pk_sha256": pq.fingerprint(pk), "not_after": None}
    try:
        with TRUST_LOCAL.open("x", encoding="ascii") as f:
            f.write(json.dumps([entry], indent=1) + "\n")
    except FileExistsError:
        print(f"kept the existing trust list in {TRUST_LOCAL.name}")
    else:
        print(f"wrote {TRUST_LOCAL.name}")
    print(f"authority ML-DSA-44 key sha256 {entry['mldsa44_pk_sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
