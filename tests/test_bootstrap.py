"""Bootstrap initializes local secrets and trust without changing existing trust decisions."""
from __future__ import annotations

import json
import os
import runpy
import stat
from pathlib import Path

import pytest
from xrpl.wallet import Wallet

from velum import config

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap.py"


def test_secret_file_is_private_when_created(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "ROOT", tmp_path)
    append_secret = runpy.run_path(str(SCRIPT))["append_secret"]
    path = tmp_path / ".env.local"
    real_fchmod = os.fchmod
    initial_modes = []

    def record_mode(fd: int, mode: int) -> None:
        initial_modes.append(stat.S_IMODE(os.fstat(fd).st_mode))
        real_fchmod(fd, mode)

    monkeypatch.setattr(os, "fchmod", record_mode)
    monkeypatch.setenv("VELUM_TEST_VALUE", "")
    previous = os.umask(0)
    try:
        append_secret("VELUM_TEST_VALUE", "first")
        path.chmod(0o644)
        append_secret("VELUM_TEST_VALUE", "second")
    finally:
        os.umask(previous)
    assert initial_modes == [0o600, 0o644]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.read_text().splitlines() == ["VELUM_TEST_VALUE=first", "VELUM_TEST_VALUE=second"]


def test_bootstrap_preserves_operator_trust_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "_loaded", True)
    monkeypatch.setenv("XRPL_NETWORK", "testnet")
    monkeypatch.setenv("VELUM_AUTHORITY_PQ_SEED", "00" * 32)
    for role in config.ROLES:
        monkeypatch.setenv(f"VELUM_SEED_{role}", "present")
    wallet = Wallet.create()
    monkeypatch.setattr(config, "wallet", lambda role: wallet)
    main = runpy.run_path(str(SCRIPT))["main"]
    assert main() == 0
    trust = tmp_path / "trust.local.json"
    entries = json.loads(trust.read_text())
    assert entries[0]["xrpl_address"] == wallet.address
    entries[0]["not_after"] = "2025-01-01T00:00:00Z"
    entries.append(dict(entries[0], xrpl_address=Wallet.create().address))
    for existing in (json.dumps(entries), "[]"):
        trust.write_text(existing)
        assert main() == 0
        assert trust.read_text() == existing
