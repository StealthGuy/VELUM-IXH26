/**
 * Read-only XRP Ledger access (VELUM.md section 7, frontend-spec.md 3.3), mirroring the Python
 * reference (velum/xrpl_ledger.py): no single node is believed.
 *
 * Each node's answer is checked without trusting the node: the transaction body (`binary: true`) must
 * hash to the requested hash, be signed by the master key of its own account, and sit in a validated
 * ledger whose header hashes to its ledger hash; the close time comes from that header. `quorum` nodes
 * must agree on index, ledger hash, close time and result. A node that is unreachable, pending, lacks
 * history or disagrees makes the lookup LedgerUnavailable ("could not verify"), never a forgery.
 */
import { sha512 } from '@noble/hashes/sha2.js'
import { decode, encodeForSigning } from 'ripple-binary-codec'
import { deriveAddress, verify as verifySignature } from 'ripple-keypairs'
import { ascii, concat, fromHex, toHex } from './bytes'

export interface Memo {
  type: string // lowercase hex
  data: string // lowercase hex
}

export interface TxInfo {
  hash: string
  validated: boolean
  result: string
  account: string
  type: string
  memos: Memo[]
  ledgerIndex: number
  closeTimeIso: string | null
}

export interface Ledger {
  readonly label: string
  /** The network a trust-list entry must name to count here ("testnet"). */
  readonly network: string
  /** null when the transaction does not exist; throws LedgerUnavailable when that cannot be decided. */
  getTx(hash: string): Promise<TxInfo | null>
}

export class LedgerUnavailable extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'LedgerUnavailable'
  }
}

/** Testnet nodes run by different operators (the Python reference uses the same three). */
export const TESTNET_ENDPOINTS = ['wss://s.altnet.rippletest.net:51233', 'wss://clio.altnet.rippletest.net:51233', 'wss://testnet.xrpl-labs.com']
export const NETWORK_IDS: Record<number, string> = { 0: 'mainnet', 1: 'testnet', 2: 'devnet' }
export const DEFAULT_QUORUM = 2
export const HISTORY_FLOOR = 1000 // a node "has full history" if its complete range starts at or below this

const RIPPLE_EPOCH = 946684800 // 2000-01-01T00:00:00Z
const TX_PREFIX = ascii('TXN\0') // HashPrefix::transactionID
const LEDGER_PREFIX = ascii('LWR\0') // HashPrefix::ledgerMaster

export function sha512Half(data: Uint8Array): Uint8Array {
  return sha512(data).subarray(0, 32)
}

/** The hash of a signed transaction blob: it covers account, type, memos and signature. */
export function txHashOf(blobHex: string): string {
  return toHex(sha512Half(concat(TX_PREFIX, fromHex(blobHex.toLowerCase())))).toUpperCase()
}

function u32(n: number): Uint8Array {
  const b = new Uint8Array(4)
  new DataView(b.buffer).setUint32(0, n)
  return b
}

/** The hash of a ledger header (it covers the close time). Throws on a malformed header. */
export function ledgerHashOf(h: Record<string, unknown>): string {
  const coins = new Uint8Array(8)
  new DataView(coins.buffer).setBigUint64(0, BigInt(String(h.total_coins)))
  const hash32 = (v: unknown) => {
    const b = fromHex(String(v).toLowerCase())
    if (b.length !== 32) throw new Error('ledger header hashes have the wrong length')
    return b
  }
  const body = concat(
    u32(Number(h.ledger_index)), coins, hash32(h.parent_hash), hash32(h.transaction_hash), hash32(h.account_hash),
    u32(Number(h.parent_close_time)), u32(Number(h.close_time)),
    new Uint8Array([Number(h.close_time_resolution), Number(h.close_flags)]),
  )
  return toHex(sha512Half(concat(LEDGER_PREFIX, body))).toUpperCase()
}

/** True if `complete_ledgers` ("209-22490748") is one range starting at or below `floor`. */
export function fullHistory(complete: unknown, floor = HISTORY_FLOOR): boolean {
  if (typeof complete !== 'string' || complete.includes(',') || !complete.includes('-')) return false
  const first = complete.split('-', 1)[0]!
  return /^\d+$/.test(first) && Number(first) <= floor
}

/** null if the transaction is single-signed by the master key of its own Account (regular keys and
 * multi-signing are not supported: the node abstains). Without this a lying node could invent a body. */
export function signatureProblem(tx: Record<string, unknown>): string | null {
  const pub = tx.SigningPubKey
  const sig = tx.TxnSignature
  if (typeof pub !== 'string' || !pub || typeof sig !== 'string') return 'the transaction is not single-signed: not supported'
  let ok = false
  try {
    if (deriveAddress(pub) !== tx.Account) return "the transaction is not signed by its account's master key"
    ok = verifySignature(encodeForSigning(tx as never), sig, pub)
  } catch {
    ok = false
  }
  return ok ? null : 'the transaction signature is invalid'
}

class Abstain extends Error {
  constructor(message: string, readonly pending = false) {
    super(message)
  }
}

/** What a node can do: answer requests. Tests pass fakes. */
export interface NodeClient {
  readonly url: string
  request(body: Record<string, unknown>): Promise<any>
  close?(): void
}

/** One WebSocket to one node; integer request ids (some servers ignore other ids). */
class WsNode implements NodeClient {
  private ws: WebSocket | null = null
  private opening: Promise<WebSocket> | null = null
  private nextId = 1
  private pending = new Map<number, { resolve: (v: any) => void; reject: (e: Error) => void }>()

  constructor(readonly url: string, readonly timeoutMs: number) {}

  private socket(): Promise<WebSocket> {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) return Promise.resolve(this.ws)
    this.opening ??= new Promise<WebSocket>((resolve, reject) => {
      let ws: WebSocket
      try {
        ws = new WebSocket(this.url)
      } catch (e) {
        reject(new Abstain(`cannot connect: ${(e as Error).message}`))
        return
      }
      const timer = setTimeout(() => {
        ws.close()
        reject(new Abstain('timeout connecting'))
      }, this.timeoutMs)
      ws.onopen = () => {
        clearTimeout(timer)
        ws.onmessage = (ev) => this.onMessage(ev)
        ws.onclose = () => this.failAll('connection closed')
        this.ws = ws
        resolve(ws)
      }
      ws.onerror = () => {
        clearTimeout(timer)
        reject(new Abstain('cannot connect'))
      }
    }).finally(() => {
      this.opening = null
    })
    return this.opening
  }

  private onMessage(ev: MessageEvent) {
    let msg: any
    try {
      msg = JSON.parse(String(ev.data))
    } catch {
      return
    }
    const p = this.pending.get(msg.id)
    if (!p) return
    this.pending.delete(msg.id)
    p.resolve(msg)
  }

  private failAll(reason: string) {
    for (const p of this.pending.values()) p.reject(new Abstain(reason))
    this.pending.clear()
    this.ws = null
  }

  async request(body: Record<string, unknown>): Promise<any> {
    const ws = await this.socket()
    const id = this.nextId++
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id)
        reject(new Abstain('request timed out'))
      }, this.timeoutMs)
      this.pending.set(id, {
        resolve: (v) => {
          clearTimeout(timer)
          resolve(v)
        },
        reject: (e) => {
          clearTimeout(timer)
          reject(e)
        },
      })
      ws.send(JSON.stringify({ id, api_version: 2, ...body }))
    })
  }

  close() {
    this.ws?.close()
    this.ws = null
  }
}

interface Found {
  tx: TxInfo
  key: string // everything the quorum must agree on
}

async function lookup(node: NodeClient, full: boolean, hash: string): Promise<Found | null> {
  const r = await node.request({ command: 'tx', transaction: hash, binary: true })
  if (r?.status === 'error' || r?.error) {
    if (r.error === 'txnNotFound') {
      if (!full) throw new Abstain('not found, but this node keeps only recent history')
      return null
    }
    throw new Abstain(`node error ${r.error}`)
  }
  const res = r?.result ?? {}
  let tx: Record<string, any>
  let meta: Record<string, any>
  let index: number
  try {
    if (txHashOf(String(res.tx_blob)) !== hash) throw new Abstain('the transaction body it returned does not have the requested hash')
    if (res.validated !== true) throw new Abstain(`transaction ${hash.slice(0, 12)}… is not validated yet`, true)
    index = Number(res.ledger_index)
    tx = decode(String(res.tx_blob)) as Record<string, any>
    meta = decode(String(res.meta_blob)) as Record<string, any>
  } catch (e) {
    if (e instanceof Abstain) throw e
    throw new Abstain(`malformed tx answer: ${(e as Error).message}`)
  }
  const problem = signatureProblem(tx)
  if (problem) throw new Abstain(problem)
  const L = await node.request({ command: 'ledger', ledger_index: index })
  const header = L?.result?.ledger
  let closeTime: number
  let ledgerHash: string
  try {
    if (L?.status === 'error' || L?.result?.validated !== true || Number(header?.ledger_index) !== index) {
      throw new Abstain(`ledger ${index} is not available as a validated ledger`)
    }
    ledgerHash = String(header.ledger_hash).toUpperCase()
    if (ledgerHashOf(header) !== ledgerHash || ledgerHash !== String(res.ledger_hash).toUpperCase()) {
      throw new Abstain(`the header of ledger ${index} does not match its hash`)
    }
    closeTime = Number(header.close_time)
  } catch (e) {
    if (e instanceof Abstain) throw e
    throw new Abstain(`malformed ledger answer: ${(e as Error).message}`)
  }
  const memos: Memo[] = ((tx.Memos ?? []) as { Memo?: { MemoType?: string; MemoData?: string } }[]).map((m) => ({
    type: String(m.Memo?.MemoType ?? '').toLowerCase(),
    data: String(m.Memo?.MemoData ?? '').toLowerCase(),
  }))
  const info: TxInfo = {
    hash,
    validated: true,
    result: String(meta.TransactionResult ?? ''),
    account: String(tx.Account ?? ''),
    type: String(tx.TransactionType ?? ''),
    memos,
    ledgerIndex: index,
    closeTimeIso: new Date((closeTime + RIPPLE_EPOCH) * 1000).toISOString().replace('.000Z', 'Z'),
  }
  return { tx: info, key: JSON.stringify([info, ledgerHash]) }
}

/** The endpoints with each normalized host and port once: two URLs for one server are one vote. */
export function distinctEndpoints(urls: string[]): string[] {
  const seen = new Set<string>()
  return urls.filter((url) => {
    let key = url
    try {
      const u = new URL(url)
      const port = u.port || ({ 'ws:': '80', 'http:': '80', 'wss:': '443', 'https:': '443' } as Record<string, string>)[u.protocol] || ''
      key = `${u.hostname.toLowerCase().replace(/\.$/, '')}:${port}`
    } catch {
      // not a URL: compare it as written
    }
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

interface ReadyNode {
  client: NodeClient
  full: boolean
}

/** A quorum of WebSocket nodes. Kept as WsLedger: the UI and the widget create it unchanged. */
export class WsLedger implements Ledger {
  private nodes: Promise<ReadyNode[]> | null = null
  private absent: string[] = []

  constructor(
    readonly endpoints: string[] = TESTNET_ENDPOINTS,
    readonly timeoutMs = 10000,
    readonly quorum = DEFAULT_QUORUM,
    readonly network = 'testnet',
    private readonly makeClient: (url: string) => NodeClient = (url) => new WsNode(url, timeoutMs),
  ) {}

  get label(): string {
    return `${this.quorum} of ${this.endpoints.length} XRPL nodes`
  }

  /** Connect and ask every node which network it serves. A node on another network, without a
   * network_id or unreachable abstains. Each host and port gets one vote (velum.xrpl_ledger). */
  private init(): Promise<ReadyNode[]> {
    this.nodes ??= (async () => {
      const ready = await Promise.all(distinctEndpoints(this.endpoints).map(async (url): Promise<ReadyNode | null> => {
        const client = this.makeClient(url)
        let info: any
        try {
          info = (await client.request({ command: 'server_info' }))?.result?.info
        } catch {
          this.absent.push(`${url}: unreachable`)
          return null
        }
        if (typeof info?.network_id !== 'number') {
          this.absent.push(`${url}: no network_id`)
          return null
        }
        const actual = NETWORK_IDS[info.network_id] ?? `network-${info.network_id}`
        if (actual !== this.network) {
          this.absent.push(`${url}: serves ${actual}, expected ${this.network}`)
          return null
        }
        return { client, full: fullHistory(info.complete_ledgers) }
      }))
      return ready.filter((n): n is ReadyNode => n !== null)
    })()
    return this.nodes
  }

  async getTx(hash: string): Promise<TxInfo | null> {
    hash = hash.toUpperCase()
    const nodes = await this.init()
    const problems = [...this.absent]
    const found: Found[] = []
    let notFound = 0
    let pending = false
    await Promise.all(nodes.map(async ({ client, full }) => {
      try {
        const answer = await lookup(client, full, hash)
        if (answer === null) notFound++
        else found.push(answer)
      } catch (e) {
        problems.push(`${client.url}: ${(e as Error).message}`)
        if (e instanceof Abstain && e.pending) pending = true
      }
    }))
    const why = problems.join('; ') || 'no node configured'
    if (found.length) {
      if (new Set(found.map((f) => f.key)).size > 1 || notFound) {
        throw new LedgerUnavailable(`nodes disagree about ${hash.slice(0, 12)}… (index, ledger hash, close time or result): cannot tell which one lies`)
      }
      if (found.length >= this.quorum) return found[0]!.tx
      throw new LedgerUnavailable(`only ${found.length} node(s) confirm ${hash.slice(0, 12)}…, ${this.quorum} required (${why})`)
    }
    if (pending) throw new LedgerUnavailable(`transaction ${hash.slice(0, 12)}… is not validated yet (${why})`)
    if (notFound >= this.quorum) return null
    throw new LedgerUnavailable(`${hash.slice(0, 12)}… not found on ${this.quorum} full-history node(s): the nodes may lack that history, or the test network was reset (${why})`)
  }

  close() {
    void this.nodes?.then((ns) => ns.forEach((n) => n.client.close?.())).catch(() => {})
    this.nodes = null
  }
}

/** In-memory ledger for tests and offline samples. Always labelled as such in the UI. */
export class MemoryLedger implements Ledger {
  readonly label = 'offline demo ledger'
  private txs: Map<string, TxInfo>

  constructor(txs: TxInfo[], readonly network = 'testnet') {
    this.txs = new Map(txs.map((t) => [t.hash, t]))
  }

  async getTx(hash: string): Promise<TxInfo | null> {
    return this.txs.get(hash) ?? null
  }
}
