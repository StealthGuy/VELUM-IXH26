/**
 * App state shared by Viewer and Editor: the loaded level, the verifier worker, XRPL status.
 * Everything stays in this tab; nothing is uploaded.
 */
import { type Check, type Report, TESTNET_ENDPOINTS, type TrustList, parseTrustList } from '~/lib/velum'
import trustListJson from '~/trust-list.json'
import type { LedgerSpec, VerifyRequest } from '~/workers/verify.worker'

/** The trust list shipped in this build. Never taken from files, URLs or the embedding page. */
export const TRUST_LIST: TrustList = parseTrustList(trustListJson) // fails loudly at build and load, never silently

export interface LoadedFile {
  name: string
  bytes: Uint8Array
}

export interface LevelFiles {
  evidence: LoadedFile | null
  sidecar: LoadedFile | null
  rendition: LoadedFile | null
  source: 'drop' | 'url' | 'sample'
  urls: { sidecar: string; evidence: string; rendition: string } | null // sidecar '' when embedded
  ledger: LedgerSpec
  /** Network the anchors are read from, for explorer links. */
  network: 'testnet'
}

export const DEFAULT_LEDGER: LedgerSpec = { kind: 'ws', endpoints: TESTNET_ENDPOINTS }


// ------------------------------------------------------------------------------------------
export type VerifierStatus = 'idle' | 'running' | 'done'

interface VerifierState {
  status: VerifierStatus
  checks: Check[]
  leaves: [number, number] | null
  log: string[]
  report: Report | null
  error: string | null
  runId: number
}

let worker: Worker | null = null

const blankChecks = (): Check[] =>
  (['V1', 'V2', 'V3', 'V4', 'V5', 'V6'] as const).map((id) => ({
    id,
    title: { V1: 'Signature', V2: "Authority's ledger record", V3: 'Pixels match the signature', V4: 'Ledger record of each level', V5: 'Redaction rules', V6: 'Published version' }[id],
    state: 'pending',
    detail: '',
    reasons: [],
    ms: null,
  }))

export function useVerifier(key = 'viewer') {
  const state = useState<VerifierState>(`velum-verifier-${key}`, () => ({ status: 'idle', checks: blankChecks(), leaves: null, log: [], report: null, error: null, runId: 0 }))

  function cancel() {
    worker?.terminate()
    worker = null
    state.value = { ...state.value, status: 'idle', runId: state.value.runId + 1 }
  }

  /** Verify a level. Resolves with the report; each run gets a fresh worker, so no stale result is reused. */
  function run(files: { evidence: Uint8Array; sidecar: Uint8Array | null; rendition: Uint8Array | null; ledger: LedgerSpec }): Promise<Report | null> {
    cancel()
    const runId = state.value.runId + 1
    state.value = { status: 'running', checks: blankChecks(), leaves: null, log: [], report: null, error: null, runId }
    const w = new Worker(new URL('../workers/verify.worker.ts', import.meta.url), { type: 'module' })
    worker = w
    const req: VerifyRequest = {
      evidence: files.evidence,
      sidecar: files.sidecar,
      rendition: files.rendition,
      trustList: JSON.parse(JSON.stringify(TRUST_LIST)),
      ledger: JSON.parse(JSON.stringify(files.ledger)),
    }
    return new Promise((resolve) => {
      w.onmessage = (ev) => {
        if (state.value.runId !== runId) return
        const m = ev.data
        if (m.type === 'progress') state.value = { ...state.value, checks: m.checks, leaves: m.leaves ?? state.value.leaves }
        else if (m.type === 'log') state.value = { ...state.value, log: [...state.value.log, m.line] }
        else if (m.type === 'done') {
          state.value = { ...state.value, status: 'done', report: m.report, checks: m.report.checks }
          w.terminate()
          if (worker === w) worker = null
          resolve(m.report)
        } else if (m.type === 'error') {
          state.value = { ...state.value, status: 'done', error: m.message }
          w.terminate()
          resolve(null)
        }
      }
      w.onerror = (e) => {
        state.value = { ...state.value, status: 'done', error: e.message || 'verifier crashed' }
        resolve(null)
      }
      w.postMessage(req)
    })
  }

  return { state, run, cancel }
}

// ------------------------------------------------------------------------------------------
export type XrplStatus = 'checking' | 'online' | 'offline'

let ledgerSocket: WebSocket | null = null
let staleTimer: ReturnType<typeof setTimeout> | undefined

/**
 * Follows the Testnet ledger stream. The header shows the latest closed ledger number,
 * which only moves while the connection is real.
 */
export function useXrplStatus() {
  const status = useState<XrplStatus>('velum-xrpl', () => 'checking')
  const ledger = useState<number | null>('velum-xrpl-ledger', () => null)
  const closedAt = useState<number | null>('velum-xrpl-closed', () => null)

  function stale() {
    clearTimeout(staleTimer)
    staleTimer = setTimeout(() => {
      status.value = 'offline'
      ledgerSocket?.close()
    }, 20000)
  }

  function connect() {
    if (!import.meta.client) return
    ledgerSocket?.close()
    status.value = 'checking'
    let ws: WebSocket
    try {
      ws = new WebSocket(TESTNET_ENDPOINTS[0]!)
    } catch {
      status.value = 'offline'
      return
    }
    ledgerSocket = ws
    stale()
    ws.onopen = () => ws.send(JSON.stringify({ id: 1, command: 'subscribe', streams: ['ledger'], api_version: 2 }))
    ws.onmessage = (ev) => {
      let m: { result?: { ledger_index?: number }; type?: string; ledger_index?: number }
      try {
        m = JSON.parse(String(ev.data))
      } catch {
        return
      }
      const idx = m.type === 'ledgerClosed' ? m.ledger_index : m.result?.ledger_index
      if (typeof idx === 'number') {
        ledger.value = idx
        closedAt.value = Date.now()
        status.value = 'online'
        stale()
      }
    }
    ws.onerror = () => {
      status.value = 'offline'
    }
    ws.onclose = () => {
      if (ledgerSocket === ws) status.value = 'offline'
    }
  }

  if (import.meta.client && !ledgerSocket) connect()
  return { status, ledger, closedAt, retry: connect }
}

// ------------------------------------------------------------------------------------------
export interface SampleIndex {
  network: 'testnet'
  samples: { id: string; label: string; level?: string; files: { evidence: string; sidecar?: string; rendition?: string } }[]
}

export async function loadSample(index: SampleIndex, id: string): Promise<LevelFiles> {
  const s = index.samples.find((x) => x.id === id)
  if (!s) throw new Error(`no sample ${id}`)
  const get = async (f: string) => ({ name: f, bytes: new Uint8Array(await (await fetch(`/samples/${id}/${f}`)).arrayBuffer()) })
  const ledger: LedgerSpec = DEFAULT_LEDGER // samples are real Testnet anchors (make demo), verified live
  return {
    evidence: await get(s.files.evidence),
    sidecar: s.files.sidecar ? await get(s.files.sidecar) : null,
    rendition: s.files.rendition ? await get(s.files.rendition) : null,
    source: 'sample',
    urls: null,
    ledger,
    network: index.network,
  }
}

export class FetchError extends Error {}

/** Fetch remote files; a failure is explained as CORS/network, never as a forgery. */
export async function loadFromUrls(urls: { sidecar: string; evidence: string; rendition: string }): Promise<LevelFiles> {
  const get = async (url: string, role: string): Promise<LoadedFile> => {
    let res: Response
    try {
      res = await fetch(url, { mode: 'cors', cache: 'no-store' })
    } catch {
      throw new FetchError(`Could not fetch the ${role} from ${new URL(url, location.href).host}. The host may not allow cross-origin reads (CORS).`)
    }
    if (!res.ok) throw new FetchError(`The ${role} URL answered ${res.status} ${res.statusText}.`)
    const name = decodeURIComponent(new URL(url, location.href).pathname.split('/').pop() || role)
    return { name, bytes: new Uint8Array(await res.arrayBuffer()) }
  }
  return {
    sidecar: urls.sidecar ? await get(urls.sidecar, 'sidecar') : null,
    evidence: await get(urls.evidence, 'evidence image'),
    rendition: urls.rendition ? await get(urls.rendition, 'rendition') : null,
    source: 'url',
    urls,
    ledger: DEFAULT_LEDGER,
    network: 'testnet',
  }
}
