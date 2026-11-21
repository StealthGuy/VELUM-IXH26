/// <reference lib="webworker" />
/** Runs verifyLevel off the main thread (frontend-spec.md 4: verify in a Web Worker). */
import { type TrustList, WsLedger, verifyLevel } from '../lib/velum'

/** Always the real ledger: the app never verifies against recorded or invented ledger data. */
export type LedgerSpec = { kind: 'ws'; endpoints: string[] }

export interface VerifyRequest {
  evidence: Uint8Array
  /** External NAME.velum.json, only needed when the evidence PNG has no embedded sidecar. */
  sidecar: Uint8Array | null
  rendition: Uint8Array | null
  trustList: TrustList
  ledger: LedgerSpec
}

self.onmessage = async (ev: MessageEvent<VerifyRequest>) => {
  const { evidence, sidecar, rendition, trustList, ledger: spec } = ev.data
  const t0 = performance.now()
  const stamp = () => ((performance.now() - t0) / 1000).toFixed(3).padStart(6, '0')
  const ledger = new WsLedger(spec.endpoints)
  try {
    const report = await verifyLevel(
      { evidence, sidecar, rendition },
      {
        trustList,
        ledger,
        onProgress: (checks, leaves) => postMessage({ type: 'progress', checks, leaves }),
        onLog: (line) => postMessage({ type: 'log', line: `${stamp()} ${line}` }),
      },
    )
    postMessage({ type: 'done', report })
  } catch (e) {
    postMessage({ type: 'error', message: (e as Error).message })
  } finally {
    ledger.close()
  }
}
