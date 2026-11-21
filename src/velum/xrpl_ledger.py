"""The real XRP Ledger: the only place that submits transactions, and the LedgerView the verifier reads.

    submit(tx, wallet)              every transaction goes through here (AGENTS.md rule 3)
    anchor(wallet, type, data)      AccountSet with exactly one memo: VELUM's only kind of write
    XrplLedger().transaction(hash)  validated history from a quorum of nodes, as velum.ledger.LedgerTx

Facts checked on real Testnet responses (api_version 2, xrpl-py 5.2): `tx` with `binary: true` returns
`tx_blob`, `meta_blob`, `validated`, `ledger_index`, `ledger_hash`; SHA-512Half("TXN\\0" + tx_blob) is the
transaction hash; `ledger` returns the header, whose SHA-512Half("LWR\\0" + fields) is `ledger_hash` and
whose `close_time` is in Ripple-epoch seconds; an unknown hash gives error `txnNotFound`; `server_info`
reports `info.network_id` (0 mainnet, 1 testnet, 2 devnet) and `info.complete_ledgers` ("209-22490748").
"""
from __future__ import annotations

import hashlib
import struct
import threading
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from xrpl.core.binarycodec import decode, encode_for_signing
from xrpl.core.keypairs import derive_classic_address, is_valid_message
from xrpl.models.requests import Ledger, ServerInfo, Tx
from xrpl.models.transactions import AccountSet, Memo
from xrpl.models.transactions.transaction import Transaction
from xrpl.transaction import XRPLReliableSubmissionException, submit_and_wait
from xrpl.wallet import Wallet

from . import config
from .ledger import RIPPLE_EPOCH, LedgerTx, LedgerUnavailable, TxNotFound


class SubmitError(RuntimeError):
    """A transaction did not end validated with tesSUCCESS. Never treated as success."""


@dataclass(frozen=True)
class Submitted:
    hash: str
    explorer_url: str


NETWORK_IDS = {0: "mainnet", 1: "testnet", 2: "devnet"}


_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _account_lock(address: str) -> threading.Lock:
    """One submission at a time per account, so sequence numbers never collide."""
    with _locks_guard:
        return _locks.setdefault(address, threading.Lock())


def submit(tx: Transaction, wallet: Wallet) -> Submitted:
    if config.network() != "testnet":
        raise SubmitError("submissions require XRPL Testnet")
    client = config.client()
    info = _server_info(client)
    network_id = info.get("network_id") if info else None
    if type(network_id) is not int or network_id != 1:
        raise SubmitError("submitting node did not confirm XRPL Testnet")
    with _account_lock(wallet.address):
        try:
            response = submit_and_wait(tx, client, wallet)
        except XRPLReliableSubmissionException as exc:
            raise SubmitError(f"{tx.transaction_type} not validated: {exc}") from exc
        except Exception as exc:  # transport error: the transaction may or may not have reached the ledger
            raise SubmitError(f"{tx.transaction_type} outcome unknown, check {wallet.address} on the explorer: "
                              f"{type(exc).__name__}: {exc}") from exc
    result: dict[str, Any] = response.result
    tx_hash = str(result.get("hash", ""))
    code = result.get("meta", {}).get("TransactionResult") if isinstance(result.get("meta"), dict) else None
    if not result.get("validated") or code != "tesSUCCESS":
        raise SubmitError(f"{tx.transaction_type} {tx_hash}: validated={result.get('validated')} result={code}")
    return Submitted(tx_hash, config.explorer_tx(tx_hash))


def anchor_tx(account: str, memo_type: str, data: bytes) -> AccountSet:
    """An AccountSet that changes nothing and carries one memo: a pure, reserve-free anchor."""
    return AccountSet(account=account, memos=[Memo(memo_type=memo_type.encode("ascii").hex().upper(),
                                                   memo_data=data.hex().upper())])


def anchor(wallet: Wallet, memo_type: str, data: bytes) -> Submitted:
    return submit(anchor_tx(wallet.address, memo_type, data), wallet)


def parse_tx(tx_hash: str, result: dict[str, Any]) -> LedgerTx:
    """Turn a `tx` response (api_version 2) into a LedgerTx. Missing fields become values that fail
    the anchor checks (not validated, empty result), never values that pass them."""
    tx_json: dict[str, Any] = result.get("tx_json") or {}
    meta = result.get("meta")
    memos = []
    for wrapper in tx_json.get("Memos") or []:
        memo = wrapper.get("Memo", {}) if isinstance(wrapper, dict) else {}
        try:
            mtype = bytes.fromhex(memo.get("MemoType", "")).decode("ascii")
            mdata = bytes.fromhex(memo.get("MemoData", ""))
        except (ValueError, UnicodeDecodeError):
            mtype, mdata = "<undecodable>", b""
        memos.append((mtype, mdata))
    date = tx_json.get("date")
    return LedgerTx(hash=tx_hash.upper(), validated=bool(result.get("validated")),
                    result=str(meta.get("TransactionResult", "")) if isinstance(meta, dict) else "",
                    tx_type=str(tx_json.get("TransactionType", "")), account=str(tx_json.get("Account", "")),
                    memos=tuple(memos), ledger_index=int(result.get("ledger_index") or 0),
                    close_time=int(date) + RIPPLE_EPOCH if isinstance(date, int) else 0)


# ---------------------------------------------------------------- reading, from several nodes
TX_PREFIX = b"TXN\x00"  # HashPrefix::transactionID
LEDGER_PREFIX = b"LWR\x00"  # HashPrefix::ledgerMaster


def sha512_half(data: bytes) -> bytes:
    return hashlib.sha512(data).digest()[:32]


def tx_hash_of(blob: bytes) -> str:
    """The hash of a signed transaction: it covers account, type, memos and signature."""
    return sha512_half(TX_PREFIX + blob).hex().upper()


def ledger_hash_of(header: dict[str, Any]) -> str:
    """The hash of a ledger header: it covers the close time. Raises on a malformed header."""
    body = (struct.pack(">IQ", int(header["ledger_index"]), int(header["total_coins"]))
            + bytes.fromhex(header["parent_hash"]) + bytes.fromhex(header["transaction_hash"])
            + bytes.fromhex(header["account_hash"])
            + struct.pack(">IIBB", int(header["parent_close_time"]), int(header["close_time"]),
                          int(header["close_time_resolution"]), int(header["close_flags"])))
    if len(body) != 4 + 8 + 3 * 32 + 4 + 4 + 2:
        raise ValueError("ledger header hashes have the wrong length")
    return sha512_half(LEDGER_PREFIX + body).hex().upper()


def full_history(complete_ledgers: object, floor: int) -> bool:
    """True if `complete_ledgers` ("209-22490748") is one range starting at or below `floor`."""
    if not isinstance(complete_ledgers, str) or "," in complete_ledgers or "-" not in complete_ledgers:
        return False
    first = complete_ledgers.split("-", 1)[0]
    return first.isdigit() and int(first) <= floor


def signature_problem(tx_json: dict[str, Any]) -> str | None:
    """None if the transaction is signed by the master key of its own Account. A hash alone proves
    nothing when the forger chose the hash (it is in the sidecar they wrote): without this a node could
    serve a made-up body for any account. Regular keys and multi-signing are not supported: abstain."""
    pub, sig = tx_json.get("SigningPubKey"), tx_json.get("TxnSignature")
    if not isinstance(pub, str) or not pub or not isinstance(sig, str):
        return "the transaction is not single-signed (multi-signed or unsigned): not supported"
    if derive_classic_address(pub) != tx_json.get("Account"):
        return "the transaction is not signed by its account's master key"
    try:
        valid = is_valid_message(bytes.fromhex(encode_for_signing(tx_json)), bytes.fromhex(sig), pub)
    except Exception:  # malformed key or signature
        valid = False
    return None if valid else "the transaction signature is invalid"


class _Abstain(Exception):
    """This node gives no usable answer (unreachable, pending, lying, history missing)."""

    def __init__(self, reason: str, pending: bool = False) -> None:
        super().__init__(reason)
        self.pending = pending


@dataclass(frozen=True)
class _Node:
    client: Any  # JsonRpcClient, or a fake in tests
    url: str
    full_history: bool


@dataclass(frozen=True)
class _Found:
    tx: LedgerTx
    ledger_hash: str


def _request(client: Any, request: Any) -> Any:
    try:
        return client.request(request)
    except Exception as exc:  # any transport problem
        raise _Abstain(f"{type(exc).__name__}: {exc}") from exc


def _lookup(node: _Node, tx_hash: str) -> _Found | None:
    """One node's answer, checked as far as it can be without trusting the node: None means "not found"."""
    response = _request(node.client, Tx(transaction=tx_hash, binary=True))
    result: dict[str, Any] = response.result
    if not response.is_successful():
        if result.get("error") == "txnNotFound":
            if not node.full_history:
                raise _Abstain("not found, but this node keeps only recent history")
            return None
        raise _Abstain(f"node error {result.get('error')}")
    try:
        if tx_hash_of(bytes.fromhex(result["tx_blob"])) != tx_hash:
            raise _Abstain("the transaction body it returned does not have the requested hash")
        if not result.get("validated"):
            raise _Abstain(f"transaction {tx_hash[:12]}… is not validated yet", pending=True)
        index = int(result["ledger_index"])
        tx_json, meta = decode(result["tx_blob"]), decode(result["meta_blob"])
        problem = signature_problem(tx_json)
        if problem:
            raise _Abstain(problem)
    except (KeyError, TypeError, ValueError) as exc:
        raise _Abstain(f"malformed tx answer: {type(exc).__name__}: {exc}") from exc
    response = _request(node.client, Ledger(ledger_index=index))
    ledger: dict[str, Any] = response.result
    try:
        header = ledger["ledger"]
        if not response.is_successful() or not ledger.get("validated") or int(header["ledger_index"]) != index:
            raise _Abstain(f"ledger {index} is not available as a validated ledger")
        if ledger_hash_of(header) != header["ledger_hash"] or header["ledger_hash"] != result.get("ledger_hash"):
            raise _Abstain(f"the header of ledger {index} does not match its hash")
        close_time = int(header["close_time"])
    except (KeyError, TypeError, ValueError) as exc:
        raise _Abstain(f"malformed ledger answer: {type(exc).__name__}: {exc}") from exc
    tx = parse_tx(tx_hash, {"validated": True, "ledger_index": index, "meta": meta,
                            "tx_json": {**tx_json, "date": close_time}})
    return _Found(tx, str(header["ledger_hash"]))


def _server_info(client: Any) -> dict[str, Any] | None:
    try:
        response = client.request(ServerInfo())
        info = response.result.get("info") if response.is_successful() else None
    except Exception:
        return None
    return info if isinstance(info, dict) else None


class XrplLedger:
    """velum.ledger.LedgerView backed by several JSON-RPC nodes of the configured network.

    No single node is believed (docs/VELUM.md section 7): each answer is checked against the requested
    transaction hash and its ledger header hash, and `quorum` nodes must agree on index, ledger hash,
    close time and result. The network name comes from the nodes themselves (server_info): a trust-list
    entry for Testnet must never count against a Mainnet node configured by mistake. A node that is
    unreachable or does not report its network abstains."""

    def __init__(self, clients: list[Any] | None = None, quorum: int | None = None,
                 history_floor: int | None = None) -> None:
        self.network = config.network()
        self.quorum = config.quorum() if quorum is None else quorum
        floor = config.history_floor() if history_floor is None else history_floor
        self.nodes: list[_Node] = []
        self.absent: list[str] = []
        seen: set[tuple[str, int | None]] = set()
        for client in (config.clients() if clients is None else clients):
            url = str(getattr(client, "url", "node"))
            endpoint = urlsplit(url)
            host = (endpoint.hostname or url).lower().rstrip(".")
            port = endpoint.port or {"http": 80, "https": 443}.get(endpoint.scheme)
            if (host, port) in seen:
                continue
            seen.add((host, port))
            info = _server_info(client)
            network_id = info.get("network_id") if info else None
            if type(network_id) is not int:
                self.absent.append(f"{url}: {'unreachable' if info is None else 'no network_id'}")
                continue  # abstains: lookups need the quorum from the other nodes
            actual = NETWORK_IDS.get(network_id, f"network-{network_id}")
            if actual != self.network:
                self.absent.append(f"{url}: serves {actual}, configuration says {self.network}")
                continue
            assert info is not None
            self.nodes.append(_Node(client, url, full_history(info.get("complete_ledgers"), floor)))

    def transaction(self, tx_hash: str) -> LedgerTx:
        tx_hash = tx_hash.upper()
        found: list[_Found] = []
        not_found, pending = 0, False
        problems = list(self.absent)
        for node in self.nodes:
            try:
                answer = _lookup(node, tx_hash)
            except _Abstain as exc:
                problems.append(f"{node.url}: {exc}")
                pending = pending or exc.pending
                continue
            except Exception as exc:  # any other malformed answer (struct, codec, wrong types): it abstains,
                problems.append(f"{node.url}: malformed answer: {type(exc).__name__}: {exc}")  # never a REJECT
                continue
            if answer is None:
                not_found += 1
            else:
                found.append(answer)
        why = "; ".join(problems) or "no node configured"
        if found:
            if len(set(found)) > 1 or not_found:
                raise LedgerUnavailable(f"nodes disagree about {tx_hash[:12]}… (index, ledger hash, close time "
                                        "or result): cannot tell which one lies")
            if len(found) >= self.quorum:
                return found[0].tx
            raise LedgerUnavailable(f"only {len(found)} node(s) confirm {tx_hash[:12]}…, {self.quorum} required "
                                    f"({why})")
        if pending:
            raise LedgerUnavailable(f"transaction {tx_hash[:12]}… is not validated yet ({why})")
        if not_found >= self.quorum:
            raise TxNotFound(tx_hash)
        raise LedgerUnavailable(f"{tx_hash[:12]}… not found on {self.quorum} full-history node(s): the nodes may "
                                f"lack that history, or the test network was reset ({why})")
