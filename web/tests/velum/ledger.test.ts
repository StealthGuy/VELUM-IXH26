/**
 * The quorum ledger client, mirroring tests/test_xrpl_ledger.py: real Testnet answers (the backend's
 * fixture, recorded from a node) replayed by fake nodes, some of them lying. No network.
 */
import { readFileSync } from 'node:fs'
import { decode, encode } from 'ripple-binary-codec'
import { generateSeed, deriveKeypair } from 'ripple-keypairs'
import { describe, expect, it } from 'vitest'
import { type NodeClient, WsLedger, distinctEndpoints, fullHistory, ledgerHashOf, txHashOf } from '../../lib/velum'

const BINARY = JSON.parse(readFileSync(new URL('../../../tests/fixtures/tx_accountset_testnet_binary.json', import.meta.url), 'utf8'))
const HASH: string = BINARY.tx.hash

interface Fake {
  url?: string
  tx?: Record<string, unknown> | null // null: txnNotFound
  ledger?: Record<string, unknown>
  history?: string
  networkId?: number | null
}

function node(f: Fake): NodeClient {
  return {
    url: f.url ?? 'fake',
    async request(body) {
      if (body.command === 'server_info') {
        return { result: { info: { network_id: f.networkId === undefined ? 1 : f.networkId ?? undefined, complete_ledgers: f.history ?? '209-22500000' } } }
      }
      if (body.command === 'tx') {
        const tx = f.tx === undefined ? BINARY.tx : f.tx
        return tx === null ? { status: 'error', error: 'txnNotFound' } : { result: tx }
      }
      if (body.command === 'ledger') return { result: f.ledger ?? BINARY.ledger }
      throw new Error(`unexpected ${String(body.command)}`)
    },
  }
}

function ledgerOf(fakes: Fake[], quorum = 2) {
  const clients = fakes.map((f, k) => node({ url: `node${k}`, ...f }))
  let k = 0
  return new WsLedger(clients.map((c) => c.url), 1000, quorum, 'testnet', () => clients[k++]!)
}

describe('hashes recomputed from real data', () => {
  it('transaction and ledger header', () => {
    expect(txHashOf(BINARY.tx.tx_blob)).toBe(HASH)
    expect(ledgerHashOf(BINARY.ledger.ledger)).toBe(BINARY.ledger.ledger_hash)
  })
})

describe('quorum', () => {
  it('two honest nodes give the facts, close time from the verified header', async () => {
    const tx = await ledgerOf([{}, {}]).getTx(HASH)
    expect(tx).toMatchObject({ hash: HASH, validated: true, result: 'tesSUCCESS', type: 'AccountSet', ledgerIndex: BINARY.tx.ledger_index })
    expect(tx!.closeTimeIso).toBe(new Date((BINARY.ledger.ledger.close_time + 946684800) * 1000).toISOString().replace('.000Z', 'Z'))
    expect(tx!.memos).toHaveLength(1)
  })
  it('one node is never enough by default', async () => {
    await expect(ledgerOf([{}]).getTx(HASH)).rejects.toThrow(/only 1 node/)
  })
  it('a different result on a third node is a disagreement', async () => {
    const meta = { ...(decode(BINARY.tx.meta_blob) as Record<string, unknown>), TransactionResult: 'tecNO_PERMISSION' }
    const failed = { ...BINARY.tx, meta_blob: encode(meta as never) } // meta is not covered by the tx hash
    await expect(ledgerOf([{}, {}, { tx: failed }]).getTx(HASH)).rejects.toThrow(/disagree/)
  })
  it('found on one node and "not found" on another is a disagreement', async () => {
    await expect(ledgerOf([{}, { tx: null }], 1).getTx(HASH)).rejects.toThrow(/disagree/)
  })
  it('not found on two full-history nodes is "not found"', async () => {
    expect(await ledgerOf([{ tx: null }, { tx: null }]).getTx(HASH)).toBeNull()
  })
})

describe('lying or limited nodes', () => {
  it('cannot answer for another hash', async () => {
    await expect(ledgerOf([{}, {}]).getTx('AB'.repeat(32))).rejects.toThrow(/does not have the requested hash/)
  })
  it('cannot change the close time', async () => {
    const header = { ...BINARY.ledger.ledger, close_time: BINARY.ledger.ledger.close_time - 86400 * 365 }
    const ledger = { ...BINARY.ledger, ledger: header }
    await expect(ledgerOf([{ ledger }, { ledger }]).getTx(HASH)).rejects.toThrow(/does not match its hash/)
  })
  it('cannot invent an anchor: the body must be signed by its account', async () => {
    const real = decode(BINARY.tx.tx_blob) as Record<string, any>
    const memo = { Memo: { MemoType: real.Memos[0].Memo.MemoType, MemoData: '00'.repeat(32) } }
    const blob = encode({ ...real, Memos: [memo] } as never)
    const tx = { ...BINARY.tx, tx_blob: blob }
    await expect(ledgerOf([{ tx }, { tx }]).getTx(txHashOf(blob))).rejects.toThrow(/signature is invalid/)
    const other = deriveKeypair(generateSeed())
    const blob2 = encode({ ...real, SigningPubKey: other.publicKey } as never)
    const tx2 = { ...BINARY.tx, tx_blob: blob2 }
    await expect(ledgerOf([{ tx: tx2 }, { tx: tx2 }]).getTx(txHashOf(blob2))).rejects.toThrow(/master key/)
  })
  it('a pending transaction is "not validated yet", never a forgery', async () => {
    const tx = { ...BINARY.tx, validated: false }
    await expect(ledgerOf([{ tx }, { tx }]).getTx(HASH)).rejects.toThrow(/not validated yet/)
  })
  it('missing history is inconclusive', async () => {
    await expect(ledgerOf([{ tx: null, history: '22488993-22490749' }, { tx: null, history: '5-10,20-30' }]).getTx(HASH))
      .rejects.toThrow(/lack that history/)
    expect(fullHistory('209-22490748')).toBe(true)
    expect(fullHistory('13073099-22490747')).toBe(false)
    expect(fullHistory('empty')).toBe(false)
    expect(fullHistory(null)).toBe(false)
  })
  it('a node without network_id or on another network abstains; the others still need the quorum', async () => {
    await expect(ledgerOf([{ networkId: null }, {}]).getTx(HASH)).rejects.toThrow(/no network_id/)
    await expect(ledgerOf([{ networkId: 0 }, {}]).getTx(HASH)).rejects.toThrow(/serves mainnet/)
    expect((await ledgerOf([{ networkId: 0 }, {}, {}]).getTx(HASH))!.result).toBe('tesSUCCESS')
    await expect(ledgerOf([{}, {}]).getTx(HASH)).resolves.not.toBeNull()
  })
  it('two URLs for the same host and port are one vote', () => {
    expect(distinctEndpoints(['wss://a.example:51233', 'wss://A.example.:51233/', 'wss://a.example:51234', 'wss://b.example', 'wss://b.example:443'])).toEqual(['wss://a.example:51233', 'wss://a.example:51234', 'wss://b.example'])
  })
})
