"""The XRPL layer, offline: parsing a real Testnet `tx` response, building anchors, configuration."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from xrpl.core.binarycodec import decode, encode
from xrpl.models.requests import Ledger, ServerInfo, Tx
from xrpl.wallet import Wallet

from velum import config, xrpl_ledger
from velum.ledger import LedgerUnavailable, TxNotFound
from velum.xrpl_ledger import (SubmitError, XrplLedger, anchor_tx, full_history, ledger_hash_of, parse_tx, submit,
                               tx_hash_of)

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "tx_accountset_testnet.json").read_text())
# the same transaction as `tx` with binary: true, and the `ledger` answer for its ledger (captured from
# s.altnet.rippletest.net, public data)
BINARY = json.loads((Path(__file__).parent / "fixtures" / "tx_accountset_testnet_binary.json").read_text())
HASH = "2B82A8F96F2A5981521FB6D0DD178642753D16962E423EBADCE69C4718F04C74"


def test_parse_a_real_testnet_anchor() -> None:
    """A real AccountSet + memo from Testnet (an ORIGO capture anchor, public data)."""
    tx = parse_tx(HASH, FIXTURE)
    assert tx.validated and tx.result == "tesSUCCESS" and tx.tx_type == "AccountSet"
    assert tx.account == FIXTURE["tx_json"]["Account"] and tx.ledger_index == 22478496
    assert len(tx.memos) == 1 and tx.memos[0][0] == "ORIGO/cap" and len(tx.memos[0][1]) == 128
    iso = datetime.fromisoformat(FIXTURE["close_time_iso"].replace("Z", "+00:00"))
    assert tx.close_time == int(iso.timestamp())  # tx_json.date + Ripple epoch == close_time_iso


def test_parse_missing_fields_never_passes() -> None:
    tx = parse_tx(HASH, {"ledger_index": 5})
    assert not tx.validated and tx.result == "" and tx.tx_type == "" and tx.memos == () and tx.close_time == 0
    broken = {**FIXTURE, "tx_json": {**FIXTURE["tx_json"], "Memos": [{"Memo": {"MemoType": "zz", "MemoData": "00"}}]}}
    assert parse_tx(HASH, broken).memos == (("<undecodable>", b""),)


def test_anchor_transaction_shape() -> None:
    tx = anchor_tx("rPT1Sjq2YGrBMTttX4GZHjKu9dyfzbpAYe", "velum/level", bytes(range(32)))
    assert tx.transaction_type == "AccountSet" and tx.set_flag is None and tx.clear_flag is None
    assert tx.memos is not None and len(tx.memos) == 1
    assert tx.memos[0].memo_type == "76656C756D2F6C6576656C"  # "velum/level", as in frontend-spec.md 3.3
    assert tx.memos[0].memo_data == bytes(range(32)).hex().upper()


def test_missing_secrets_fail_without_revealing_anything(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VELUM_SEED_LAB", raising=False)
    monkeypatch.setattr(config, "_loaded", True)  # do not read the developer's .env.local in tests
    with pytest.raises(RuntimeError, match="make bootstrap"):
        config.wallet("LAB")
    monkeypatch.setenv("VELUM_AUTHORITY_PQ_SEED", "abc")
    with pytest.raises(RuntimeError, match="make bootstrap"):
        config.authority_pq_seed()


def test_env_file_parsing(tmp_path: Path) -> None:
    f = tmp_path / ".env"
    f.write_text("# comment\nXRPL_NETWORK=testnet\n\nBAD LINE\nKEY = value with = sign\n")
    assert config._parse(f) == {"XRPL_NETWORK": "testnet", "KEY": "value with = sign"}


# ---------------------------------------------------------------- review fixes (fake node, no network)
class FakeResponse:
    def __init__(self, result: dict[str, Any], ok: bool = True) -> None:
        self.result, self._ok = result, ok

    def is_successful(self) -> bool:
        return self._ok


class FakeClient:
    """A node that answers `server_info`, `tx` (binary) and `ledger` from captured Testnet data."""

    def __init__(self, network_id: int | None = 1, tx: dict[str, Any] | None = None, down: bool = False,
                 history: str = "1-99999999", ledger: dict[str, Any] | None = None, url: str = "fake") -> None:
        self.network_id, self.tx, self.down, self.history, self.url = network_id, tx, down, history, url
        self.ledger = ledger or BINARY["ledger"]

    def request(self, req: object) -> FakeResponse:
        if self.down:
            raise ConnectionError("node down")
        if isinstance(req, ServerInfo):
            return FakeResponse({"info": {"network_id": self.network_id, "complete_ledgers": self.history}})
        if isinstance(req, Ledger):
            return FakeResponse(self.ledger)
        assert isinstance(req, Tx) and req.binary
        return FakeResponse(self.tx or {"error": "txnNotFound"}, ok=self.tx is not None)


def use_node(monkeypatch: pytest.MonkeyPatch, *nodes: FakeClient, quorum: int = 1) -> None:
    monkeypatch.setattr(config, "clients", lambda: list(nodes))
    monkeypatch.setenv("XRPL_NETWORK", "testnet")
    monkeypatch.setenv("XRPL_QUORUM", str(quorum))


def test_network_comes_from_the_node(monkeypatch: pytest.MonkeyPatch) -> None:
    use_node(monkeypatch, FakeClient(network_id=1))
    assert XrplLedger().network == "testnet"
    use_node(monkeypatch, FakeClient(network_id=0))  # a Mainnet node configured as "testnet"
    with pytest.raises(LedgerUnavailable, match="serves mainnet"):
        XrplLedger().transaction(HASH)
    use_node(monkeypatch, FakeClient(network_id=0), FakeClient(tx=BINARY["tx"], url="a"),
             FakeClient(tx=BINARY["tx"], url="b"), quorum=2)
    assert XrplLedger().transaction(HASH).hash == HASH
    use_node(monkeypatch, FakeClient(down=True))  # unreachable: keep the label, lookups will be unverifiable
    assert XrplLedger().network == "testnet"


def test_pending_transaction_is_unverifiable_not_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    use_node(monkeypatch, FakeClient(tx={**BINARY["tx"], "validated": False}))
    with pytest.raises(LedgerUnavailable, match="not validated yet"):
        XrplLedger().transaction(HASH)


def test_unknown_and_validated_transactions(monkeypatch: pytest.MonkeyPatch) -> None:
    use_node(monkeypatch, FakeClient(tx=None))
    with pytest.raises(TxNotFound):
        XrplLedger().transaction(HASH)
    use_node(monkeypatch, FakeClient(tx=BINARY["tx"]))
    assert XrplLedger().transaction(HASH).result == "tesSUCCESS"


def test_submit_never_reports_success_it_did_not_see(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "client", lambda: FakeClient())
    monkeypatch.setenv("XRPL_NETWORK", "testnet")
    wallet = Wallet.create()
    tx = anchor_tx(wallet.address, "velum/level", bytes(32))

    def network_down(*args: object, **kwargs: object) -> object:
        raise ConnectionError("connection reset")

    monkeypatch.setattr(xrpl_ledger, "submit_and_wait", network_down)
    with pytest.raises(SubmitError, match="outcome unknown"):
        submit(tx, wallet)

    def tec(*args: object, **kwargs: object) -> FakeResponse:
        return FakeResponse({"hash": "AB" * 32, "validated": True, "ledger_index": 7,
                             "meta": {"TransactionResult": "tecNO_PERMISSION"}})

    monkeypatch.setattr(xrpl_ledger, "submit_and_wait", tec)
    with pytest.raises(SubmitError, match="tecNO_PERMISSION"):
        submit(tx, wallet)


# ---------------------------------------------------------------- audit fixes: no single node is believed
def test_hashes_are_recomputed_from_real_data() -> None:
    assert tx_hash_of(bytes.fromhex(BINARY["tx"]["tx_blob"])) == HASH
    assert ledger_hash_of(BINARY["ledger"]["ledger"]) == BINARY["ledger"]["ledger_hash"]


def test_binary_answer_gives_the_same_facts_as_the_json_one(monkeypatch: pytest.MonkeyPatch) -> None:
    use_node(monkeypatch, FakeClient(tx=BINARY["tx"]))
    assert XrplLedger().transaction(HASH) == parse_tx(HASH, FIXTURE)  # close time from the verified header


def test_a_node_cannot_answer_for_another_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    """A lying node returns a real transaction body under a hash it does not have."""
    use_node(monkeypatch, FakeClient(tx=BINARY["tx"]))
    with pytest.raises(LedgerUnavailable, match="does not have the requested hash"):
        XrplLedger().transaction("AB" * 32)


def test_a_node_cannot_change_the_close_time(monkeypatch: pytest.MonkeyPatch) -> None:
    header = {**BINARY["ledger"]["ledger"], "close_time": BINARY["ledger"]["ledger"]["close_time"] - 86400 * 365}
    use_node(monkeypatch, FakeClient(tx=BINARY["tx"], ledger={**BINARY["ledger"], "ledger": header}))
    with pytest.raises(LedgerUnavailable, match="does not match its hash"):
        XrplLedger().transaction(HASH)


def test_quorum_and_disagreement(monkeypatch: pytest.MonkeyPatch) -> None:
    honest = FakeClient(tx=BINARY["tx"], url="a")
    use_node(monkeypatch, honest, quorum=2)  # one node is never enough by default
    with pytest.raises(LedgerUnavailable, match="only 1 node"):
        XrplLedger().transaction(HASH)
    use_node(monkeypatch, honest, FakeClient(tx=BINARY["tx"], url="b"), quorum=2)
    assert XrplLedger().transaction(HASH).result == "tesSUCCESS"
    meta = {**decode(BINARY["tx"]["meta_blob"]), "TransactionResult": "tecNO_PERMISSION"}
    failed = {**BINARY["tx"], "meta_blob": encode(meta)}  # meta is not covered by the transaction hash
    use_node(monkeypatch, honest, FakeClient(tx=BINARY["tx"], url="b"), FakeClient(tx=failed, url="c"), quorum=2)
    with pytest.raises(LedgerUnavailable, match="disagree"):
        XrplLedger().transaction(HASH)
    use_node(monkeypatch, honest, FakeClient(tx=None, url="b"), quorum=1)  # found here, "not found" there
    with pytest.raises(LedgerUnavailable, match="disagree"):
        XrplLedger().transaction(HASH)


def test_missing_history_is_unverifiable_not_forged(monkeypatch: pytest.MonkeyPatch) -> None:
    recent = FakeClient(tx=None, history="22488993-22490749")  # like testnet.xrpl-labs.com today
    use_node(monkeypatch, recent)
    with pytest.raises(LedgerUnavailable, match="lack that history"):
        XrplLedger().transaction(HASH)
    use_node(monkeypatch, FakeClient(tx=None, history="5-10,20-30"))  # gaps: not full history either
    with pytest.raises(LedgerUnavailable):
        XrplLedger().transaction(HASH)
    assert full_history("209-22490748", 1000) and not full_history("13073099-22490747", 1000)
    assert not full_history("empty", 1000) and not full_history(None, 1000)


def test_a_node_without_network_id_abstains(monkeypatch: pytest.MonkeyPatch) -> None:
    use_node(monkeypatch, FakeClient(network_id=None, tx=BINARY["tx"]))
    ledger = XrplLedger()
    assert ledger.nodes == []
    with pytest.raises(LedgerUnavailable, match="no network_id"):
        ledger.transaction(HASH)


def test_quoted_values_in_env_files(tmp_path: Path) -> None:
    f = tmp_path / ".env.local"
    f.write_text('A="quoted"\nB=\'single\'\nC="unbalanced\n')
    assert config._parse(f) == {"A": "quoted", "B": "single", "C": '"unbalanced'}


def test_a_node_cannot_invent_an_anchor_for_an_account(monkeypatch: pytest.MonkeyPatch) -> None:
    """The forger chooses the hash (it is in the sidecar), so a hash check alone is not enough: the body
    must also be signed by the account it claims to come from."""
    real = decode(BINARY["tx"]["tx_blob"])
    fake = {**real, "Memos": [{"Memo": {"MemoType": real["Memos"][0]["Memo"]["MemoType"], "MemoData": "00" * 32}}]}
    blob = encode(fake)  # the real signature does not cover the new memo
    use_node(monkeypatch, FakeClient(tx={**BINARY["tx"], "tx_blob": blob}))
    with pytest.raises(LedgerUnavailable, match="signature is invalid"):
        XrplLedger().transaction(tx_hash_of(bytes.fromhex(blob)))
    other = Wallet.create()  # signed, but by a key that is not the account's
    fake = {**real, "SigningPubKey": other.public_key}
    blob = encode(fake)
    use_node(monkeypatch, FakeClient(tx={**BINARY["tx"], "tx_blob": blob}))
    with pytest.raises(LedgerUnavailable, match="master key"):
        XrplLedger().transaction(tx_hash_of(bytes.fromhex(blob)))


def test_quorum_counts_distinct_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    for tx in (BINARY["tx"], None):
        clients = [FakeClient(tx=tx, url=url) for url in
                   ("https://NODE.example", "https://node.example.:443/", "https://node.example/rpc")]
        use_node(monkeypatch, *clients, quorum=2)
        ledger = XrplLedger()
        assert len(ledger.nodes) == 1
        with pytest.raises(LedgerUnavailable):
            ledger.transaction(HASH)


@pytest.mark.parametrize(("configured", "reported"), [("mainnet", 1), ("testnet", 0), ("testnet", None),
                                                        ("testnet", True)])
def test_submit_checks_testnet_before_signing(monkeypatch: pytest.MonkeyPatch, configured: str,
                                               reported: int | None) -> None:
    monkeypatch.setenv("XRPL_NETWORK", configured)
    monkeypatch.setattr(config, "client", lambda: FakeClient(network_id=reported))
    monkeypatch.setattr(xrpl_ledger, "submit_and_wait", lambda *args: pytest.fail("unexpected submission"))
    wallet = Wallet.create()
    with pytest.raises(SubmitError, match="Testnet"):
        submit(anchor_tx(wallet.address, "velum/level", bytes(32)), wallet)


class OddClient(FakeClient):
    """A node whose `tx` error answer is not even a JSON object."""

    def request(self, req: object) -> FakeResponse:
        response = super().request(req)
        return FakeResponse([], ok=False) if isinstance(req, Tx) else response  # type: ignore[arg-type]


def test_a_malformed_answer_makes_the_node_abstain_not_reject(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neither meta_blob nor the header numbers are covered by the transaction hash: one hostile node
    must not turn a genuine anchor into an error that the verifier would report as a REJECT."""
    honest = [FakeClient(tx=BINARY["tx"], url="a"), FakeClient(tx=BINARY["tx"], url="b")]
    huge = {**BINARY["ledger"]["ledger"], "total_coins": str(2**64)}  # struct.error, not a ValueError
    bad_meta = {**BINARY["tx"], "meta_blob": "0000"}  # XRPLBinaryCodecException, not a ValueError
    for hostile in (FakeClient(tx=BINARY["tx"], ledger={**BINARY["ledger"], "ledger": huge}, url="c"),
                    FakeClient(tx=bad_meta, url="c"), OddClient(tx=BINARY["tx"], url="c")):
        use_node(monkeypatch, hostile, quorum=1)
        with pytest.raises(LedgerUnavailable, match="c: "):
            XrplLedger().transaction(HASH)
        use_node(monkeypatch, *honest, hostile, quorum=2)  # the honest quorum still decides
        assert XrplLedger().transaction(HASH).result == "tesSUCCESS"
