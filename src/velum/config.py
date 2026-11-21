"""Configuration. Public settings come from `.env`, secrets from `.env.local` (AGENTS.md rule 2).

Secrets are read here and nowhere else, and are never printed, logged or returned to a caller as text:
    VELUM_SEED_<ROLE>          XRPL seed of a role (AUTHORITY, LAB, NEWSROOM), written by `make bootstrap`
    VELUM_AUTHORITY_PQ_SEED    32-byte hex seed of the authority's ML-DSA-44 key

Public settings (all optional):
    XRPL_RPC_URL               the node that submits transactions
    XRPL_RPC_URLS              comma-separated nodes the verifier asks (docs/VELUM.md section 7)
    XRPL_QUORUM                how many of them must confirm a transaction (default 2)
    XRPL_HISTORY_FLOOR         a node whose history starts at or below this ledger is full-history
    VELUM_MASTER_DIR           private folder for the authority's per-image secrets (~/.velum/masters)
    VELUM_MAX_VERIFY_PIXELS    the verifier's pixel budget (default 2^23)
"""
from __future__ import annotations

import os
from pathlib import Path

from xrpl.clients import JsonRpcClient
from xrpl.wallet import Wallet

ROOT = Path(__file__).resolve().parents[2]  # repository root: VELUM runs from its repo (src layout, pip -e)
ROLES = ("AUTHORITY", "LAB", "NEWSROOM")
# Public Testnet JSON-RPC nodes. The first two are run by Ripple (clio keeps full history), the third by
# XRPL Labs (recent history only). Prefer nodes of independent operators when you configure your own.
DEFAULT_VERIFY_URLS = ("https://s.altnet.rippletest.net:51234/", "https://clio.altnet.rippletest.net:51234/",
                       "https://testnet.xrpl-labs.com/")
_loaded = False


def _parse(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]  # KEY="value" means value, as in a shell
                out[key.strip()] = value
    return out


def load_env() -> None:
    """Read .env then .env.local into os.environ, without overriding variables already set."""
    global _loaded
    if not _loaded:
        for name in (".env", ".env.local"):
            for key, value in _parse(ROOT / name).items():
                os.environ.setdefault(key, value)
        _loaded = True


def network() -> str:
    load_env()
    return os.environ.get("XRPL_NETWORK", "testnet")


def rpc_url() -> str:
    load_env()
    return os.environ.get("XRPL_RPC_URL", "https://s.altnet.rippletest.net:51234/")


def explorer_tx(tx_hash: str) -> str:
    load_env()
    return os.environ.get("XRPL_EXPLORER_TX", "https://testnet.xrpl.org/transactions/") + tx_hash


def client() -> JsonRpcClient:
    return JsonRpcClient(rpc_url())


def verify_urls() -> list[str]:
    load_env()
    urls = [u.strip() for u in os.environ.get("XRPL_RPC_URLS", "").split(",") if u.strip()]
    return urls or list(DEFAULT_VERIFY_URLS)


def clients() -> list[JsonRpcClient]:
    """The nodes the verifier asks (never one alone: docs/VELUM.md section 7)."""
    return [JsonRpcClient(url) for url in verify_urls()]


def _int_setting(name: str, default: int, lo: int) -> int:
    load_env()
    raw = os.environ.get(name, "")
    try:
        value = int(raw) if raw else default
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value < lo:
        raise RuntimeError(f"{name} must be at least {lo}")
    return value


def quorum() -> int:
    return _int_setting("XRPL_QUORUM", 2, 1)


def history_floor() -> int:
    return _int_setting("XRPL_HISTORY_FLOOR", 1000, 1)


def max_verify_pixels() -> int:
    return _int_setting("VELUM_MAX_VERIFY_PIXELS", 1 << 23, 1)


def master_dir() -> Path:
    load_env()
    return Path(os.environ.get("VELUM_MASTER_DIR") or Path.home() / ".velum" / "masters").expanduser()


def wallet(role: str) -> Wallet:
    """The XRPL wallet of a role. Raises without revealing anything if the seed is missing."""
    load_env()
    seed = os.environ.get(f"VELUM_SEED_{role}")
    if not seed:
        raise RuntimeError(f"no wallet for {role}: run `make bootstrap`")
    return Wallet.from_seed(seed)


def authority_pq_seed() -> bytes:
    load_env()
    value = os.environ.get("VELUM_AUTHORITY_PQ_SEED", "")
    if len(value) != 64:
        raise RuntimeError("no authority ML-DSA seed: run `make bootstrap`")
    return bytes.fromhex(value)
