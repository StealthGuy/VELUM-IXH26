"""What the verifier needs from the XRP Ledger, as an interface (docs/VELUM.md section 7).

The real implementation (build step 2) reads validated transactions from an XRPL node. Tests use an
in-memory ledger; the application never does (AGENTS.md rule 1).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

RIPPLE_EPOCH = 946_684_800  # 2000-01-01T00:00:00Z in Unix seconds


class LedgerUnavailable(Exception):
    """The ledger could not be reached: the result is "could not verify", never a forgery."""


class TxNotFound(LookupError):
    """No validated transaction with this hash."""


@dataclass(frozen=True)
class LedgerTx:
    hash: str
    validated: bool
    result: str  # e.g. "tesSUCCESS"
    tx_type: str  # e.g. "AccountSet"
    account: str
    memos: tuple[tuple[str, bytes], ...]  # (MemoType decoded as text, MemoData bytes)
    ledger_index: int
    close_time: int  # Unix seconds of the ledger that contains the transaction


class LedgerView(Protocol):
    network: str  # e.g. "testnet": a trust-list entry only counts on its own network

    def transaction(self, tx_hash: str) -> LedgerTx:
        """Raise TxNotFound or LedgerUnavailable instead of returning anything doubtful."""
        ...


def anchor_problem(tx: LedgerTx, account: str, memo_type: str, data: bytes) -> str | None:
    """None if `tx` anchors `data` as required; otherwise the reason it does not."""
    if not tx.validated:
        return "transaction is not validated"
    if tx.result != "tesSUCCESS":
        return f"transaction result is {tx.result}"
    if tx.tx_type != "AccountSet":
        return f"transaction type is {tx.tx_type}, expected AccountSet"
    if tx.account != account:
        return f"sent by {tx.account}, expected {account}"
    if len(tx.memos) != 1:
        return f"{len(tx.memos)} memos, expected exactly one"
    mtype, mdata = tx.memos[0]
    if mtype != memo_type:
        return f"memo type {mtype!r}, expected {memo_type!r}"
    if mdata != data:
        return "memo data does not match"
    return None
