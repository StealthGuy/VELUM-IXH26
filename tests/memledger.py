"""TEST ONLY: an in-memory stand-in for validated XRPL history (AGENTS.md rule 1).

Every anchor closes a new 'ledger' 4 seconds after the previous one. Transaction hashes are fake but
deterministic, so test vectors are reproducible. Never import this outside tests/ and scripts/make_vectors.py.
"""
from __future__ import annotations

import hashlib
from collections.abc import Sequence

from velum.ledger import LedgerTx, LedgerUnavailable, TxNotFound

START_INDEX = 1000
START_TIME = 1_800_000_000  # 2027-01-15


class MemLedger:
    def __init__(self) -> None:
        self.network = "testnet"
        self.txs: dict[str, LedgerTx] = {}
        self.index = START_INDEX
        self.time = START_TIME
        self.down = False  # simulate an unreachable node

    def anchor(self, account: str, memo_type: str, data: bytes, *, result: str = "tesSUCCESS",
               tx_type: str = "AccountSet", extra_memos: Sequence[tuple[str, bytes]] = ()) -> str:
        self.index += 1
        self.time += 4
        tx_hash = hashlib.sha256(f"{self.index}|{account}|{memo_type}|{data.hex()}".encode()).hexdigest().upper()
        self.txs[tx_hash] = LedgerTx(hash=tx_hash, validated=True, result=result, tx_type=tx_type, account=account,
                                     memos=((memo_type, data), *extra_memos), ledger_index=self.index,
                                     close_time=self.time)
        return tx_hash

    def transaction(self, tx_hash: str) -> LedgerTx:
        if self.down:
            raise LedgerUnavailable("simulated network failure")
        if tx_hash not in self.txs:
            raise TxNotFound(tx_hash)
        return self.txs[tx_hash]
