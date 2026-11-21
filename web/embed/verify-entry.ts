/**
 * Lazy chunk of the embed widget: the full verifier (ML-DSA included) and the trust list
 * bundled at build time. Loaded only when a reader clicks a badge.
 */
import { WsLedger, parseTrustList, verifyLevel } from '../lib/velum'
import trustListJson from '../trust-list.json'

const trustList = parseTrustList(trustListJson)

export interface EmbedResult {
  verdict: 'verified' | 'rejected' | 'unknown'
  authority: string | null
  signedAt: string | null
  hiddenPct: string
  hiddenTiles: number
  /** Where the sidecar came from: embedded in the PNG or a separate file. */
  sidecar: 'embedded' | 'external' | null
  failed: string[]
}

async function bytes(url: string): Promise<Uint8Array> {
  const r = await fetch(url, { mode: 'cors', credentials: 'omit', cache: 'no-store' })
  if (!r.ok) throw new Error(`${r.status} for ${url}`)
  return new Uint8Array(await r.arrayBuffer())
}

/** `sidecar` is optional: the evidence PNG normally carries it (zTXt velum.sidecar). */
export async function verifyEmbedded(urls: { sidecar: string | null; evidence: string; image: string }): Promise<EmbedResult> {
  let sidecar: Uint8Array | null, evidence: Uint8Array, image: Uint8Array
  try {
    ;[sidecar, evidence, image] = await Promise.all([urls.sidecar ? bytes(urls.sidecar) : null, bytes(urls.evidence), bytes(urls.image)])
  } catch {
    return { verdict: 'unknown', authority: null, signedAt: null, hiddenPct: '', hiddenTiles: 0, sidecar: null, failed: ['fetch'] }
  }
  const sameAsEvidence = urls.image === urls.evidence
  const ledger = new WsLedger()
  try {
    const r = await verifyLevel({ evidence, sidecar, rendition: sameAsEvidence ? null : image }, { trustList, ledger })
    const n = r.cols * r.rows
    const hidden = r.hiddenLevel.filter((k) => k >= 0).length
    return {
      verdict: r.verdict,
      authority: r.authority?.name ?? null,
      signedAt: r.signedAt,
      hiddenPct: n ? `${((hidden / n) * 100).toFixed(1)}%` : '',
      hiddenTiles: hidden,
      sidecar: r.sidecarSource,
      failed: r.checks.filter((c) => c.state === 'fail').map((c) => c.id),
    }
  } finally {
    ledger.close()
  }
}
