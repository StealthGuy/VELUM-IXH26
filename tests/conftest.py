"""Shared test setup: the authority's masters go to a temporary folder, never to the developer's home."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def private_master_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "masters"
    folder.mkdir(mode=0o700)
    monkeypatch.setenv("VELUM_MASTER_DIR", str(folder))
    return folder
