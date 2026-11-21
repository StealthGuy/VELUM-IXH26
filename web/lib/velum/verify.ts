/**
 * Verification V1-V6 (VELUM.md section 7), mirroring the Python reference (velum/verify.py).
 * Runs every check, never throws, returns a plain structured-cloneable report so it can cross a
 * Web Worker boundary.
 *
 * Verdicts: 'verified' (ACCEPT) every check passed; 'rejected' (REJECT) a check failed for a reason
 * that says something about authenticity; 'unknown' (UNVERIFIABLE) the only problems are inconclusive:
 * the ledger could not answer, a transaction is not validated yet, or the image is above this
 * verifier's pixel budget. Any unexpected error inside a check is a failure (fail closed).
 */
import { ascii, equal, fromHex, toHex } from './bytes'
import { canonicalBytes } from './canonical'
import { sha256 } from './hash'
import type { Image } from './image'
import { type Ledger, LedgerUnavailable, type TxInfo } from './ledger'
import { merkleRoot } from './merkle'
import { MAX_SIDECAR, OverBudget, PngError, SidecarChunkError, readPng, readSidecar } from './png'
import { MANIFEST_CTX, fingerprint, verify as pqVerify } from './pq'
import { applyRecipe, outputSize } from './recipe'
import { type Crop, type Descriptor, type Manifest, type Recipe, type Sidecar, bitmapToSet, cropFits, parseSidecarText, tilesOutsideCrop } from './sidecar'
import { Grid, leafHash, tileBytes, tileIsBlack } from './tiles'
import { type TrustList, findAuthority, findByAddress } from './trust'

export type CheckId = 'V1' | 'V2' | 'V3' | 'V4' | 'V5' | 'V6'
export type CheckState = 'pending' | 'running' | 'pass' | 'fail' | 'unknown' | 'skipped'
export type Verdict = 'verified' | 'rejected' | 'unknown'

/** Verifier policy, not a format limit (VELUM.md 3): pixels this verifier agrees to decode. */
export const VERIFY_PIXELS = 2 ** 23

export interface Check {
  id: CheckId
  title: string
  state: CheckState
  detail: string
  reasons: string[]
  ms: number | null
}

export interface LevelInfo {
  index: number
  producer: string
  tx: string
  ledgerIndex: number | null
  time: string | null
  added: number[]
  hiddenCount: number
  crop: Crop | null
  recipe: Recipe | null
}

export interface Report {
  verdict: Verdict
  /** A reason that stopped verification before the checks (unreadable file, network): verdict 'unknown'. */
  error: string | null
  checks: Check[]
  manifest: Manifest | null
  authority: { name: string | null; address: string; network: string | null } | null
  signedAt: string | null
  /** Where the sidecar came from: embedded in the evidence PNG (preferred) or an external file. */
  sidecarSource: 'embedded' | 'external' | null
  width: number
  height: number
  cols: number
  rows: number
  /** For every tile: 1 when hidden in this copy (the index of its only level), -1 when visible. */
  hiddenLevel: number[]
  /** Tiles outside the level's crop. */
  cropped: number[]
  /** Hidden tiles whose real pixels are not black (V3). */
  badTiles: number[]
  /** This copy (one entry: a sidecar carries no chain of custody). */
  levels: LevelInfo[]
  computedRoot: string | null
  rendition: { width: number; height: number } | null
  ledger: string
  ms: number
}

export interface VerifyInput {
  evidence: Uint8Array
  /** An external NAME.velum.json; used only when the evidence PNG carries no embedded sidecar. */
  sidecar?: string | Uint8Array | null
  rendition?: Uint8Array | null
}

export interface VerifyOptions {
  trustList: TrustList
  ledger: Ledger
  maxPixels?: number
  onProgress?: (checks: Check[], leaves: [number, number] | null) => void
  onLog?: (line: string) => void
}

export const CHECK_TITLES: Record<CheckId, string> = {
  V1: 'Signature',
  V2: "Authority's ledger record",
  V3: 'Pixels match the signature',
  V4: "This copy's ledger record",
  V5: 'Redaction rules',
  V6: 'Published version',
}

export const MEMO_MANIFEST = toHex(ascii('velum/manifest'))
export const MEMO_LEVEL = toHex(ascii('velum/level'))

export function descriptorHash(d: Descriptor): string {
  return toHex(sha256(canonicalBytes(d)))
}

export function manifestMemoData(m: Manifest, sigHex: string): string {
  return toHex(sha256(canonicalBytes(m))) + toHex(sha256(fromHex(sigHex)))
}

const short = (s: string, a = 4, b = 4) => (s.length > a + b + 1 ? `${s.slice(0, a)}…${s.slice(-b)}` : s)

/** Checks an anchor tx; returns a list of problems (empty = anchored). */
function anchorProblems(tx: TxInfo | null, account: string, memoType: string, memoData: string): string[] {
  if (!tx) return ['transaction not found on the ledger']
  const p: string[] = []
  if (!tx.validated) p.push('transaction is not in a validated ledger')
  if (tx.result !== 'tesSUCCESS') p.push(`result is ${tx.result || 'missing'}, not tesSUCCESS`)
  if (tx.type !== 'AccountSet') p.push(`type is ${tx.type}, not AccountSet`)
  if (tx.account !== account) p.push(`sent by ${tx.account}, expected ${account}`)
  if (tx.memos.length !== 1) p.push(`has ${tx.memos.length} memos, expected exactly 1`)
  else {
    if (tx.memos[0]!.type !== memoType) p.push('memo type is not ' + new TextDecoder().decode(fromHex(memoType)))
    if (tx.memos[0]!.data !== memoData) p.push('memo data does not match')
  }
  return p
}

/** The external sidecar as text; bytes that are not ASCII cannot be a sidecar. */
function externalText(v: string | Uint8Array | null | undefined): string | null {
  if (v === null || v === undefined) return null
  if (v.length > MAX_SIDECAR) throw new Error(`the external sidecar exceeds ${MAX_SIDECAR} bytes`)
  if (typeof v === 'string') return v
  if (v.some((b) => b > 0x7f)) throw new Error('the external sidecar file is not ASCII')
  return new TextDecoder('ascii').decode(v)
}

export async function verifyLevel(input: VerifyInput, opts: VerifyOptions): Promise<Report> {
  const t0 = performance.now()
  const maxPixels = Math.min(opts.maxPixels ?? VERIFY_PIXELS, 2 ** 25)
  const log = (s: string) => opts.onLog?.(s)
  const checks: Check[] = (Object.keys(CHECK_TITLES) as CheckId[]).map((id) => ({
    id, title: CHECK_TITLES[id], state: 'pending', detail: '', reasons: [], ms: null,
  }))
  const report: Report = {
    verdict: 'unknown', error: null, checks, manifest: null, authority: null, signedAt: null, sidecarSource: null,
    width: 0, height: 0, cols: 0, rows: 0, hiddenLevel: [], cropped: [], badTiles: [], levels: [],
    computedRoot: null, rendition: null, ledger: opts.ledger.label, ms: 0,
  }
  const emit = (leaves: [number, number] | null = null) => opts.onProgress?.(checks.map((c) => ({ ...c, reasons: [...c.reasons] })), leaves)
  const get = (id: CheckId) => checks.find((c) => c.id === id)!
  let started = 0
  const start = (id: CheckId) => {
    get(id).state = 'running'
    started = performance.now()
    emit()
  }
  const finish = (id: CheckId, state: CheckState, detail: string, reasons: string[] = []) => {
    Object.assign(get(id), { state, detail, reasons, ms: Math.round(performance.now() - started) })
    log(`${id} ${state}${reasons.length ? ' · ' + reasons[0] : ''}`)
    emit()
  }
  /** A ledger problem is inconclusive; anything else unexpected is a failure (fail closed). */
  const ledgerError = (id: CheckId, e: unknown) => e instanceof LedgerUnavailable
    ? finish(id, 'unknown', 'The XRP Ledger could not confirm this record yet.', [(e as Error).message])
    : finish(id, 'fail', 'Reading the ledger failed.', [`internal error: ${(e as Error).message}`])
  const done = () => {
    const states = checks.map((c) => c.state)
    report.verdict = states.includes('fail') ? 'rejected' : states.some((s) => s !== 'pass' && s !== 'skipped') || report.error ? 'unknown' : 'verified'
    report.ms = Math.round(performance.now() - t0)
    return report
  }
  // --- V1 signature (the sidecar: embedded in the PNG first, then the external file) ---------
  start('V1')
  let sc: Sidecar
  try {
    let embedded: string | null = null
    try {
      embedded = await readSidecar(input.evidence)
    } catch (e) {
      if (e instanceof SidecarChunkError) throw e // a broken embedded sidecar is an error, not "no sidecar"
      if (!(e instanceof PngError)) throw e
      if (input.sidecar == null) throw new Error(`no sidecar: the evidence PNG is unreadable (${e.message}) and no external file was given`)
    }
    const text = embedded ?? externalText(input.sidecar)
    if (text === null) throw new Error('no sidecar: none embedded in the PNG and no external file given')
    report.sidecarSource = embedded !== null ? 'embedded' : 'external'
    sc = parseSidecarText(text)
  } catch (e) {
    finish('V1', 'fail', 'The sidecar is not a valid VELUM file.', [(e as Error).message])
    // like the Python reference: without a valid sidecar no other check can pass
    for (const c of checks) if (c.state === 'pending') Object.assign(c, { state: 'fail', detail: 'Not run: invalid sidecar.', reasons: ['not run: invalid sidecar'] })
    emit()
    return done()
  }
  const m = sc.manifest
  const d = sc.level
  const grid = new Grid(m.w, m.h)
  Object.assign(report, { manifest: m, width: m.w, height: m.h, cols: grid.cols, rows: grid.rows })
  log(`sidecar ${report.sidecarSource} · ${grid.n} tiles`)
  const pk = fromHex(sc.authority_pk)
  const pkHash = fingerprint(pk)
  const entry = findAuthority(opts.trustList, opts.ledger.network, m.authority, pkHash)
  const pinned = opts.trustList.entries.find((e) => e.xrpl_address === m.authority && e.mldsa44_pk_sha256 === pkHash) // for the message only
  const sameAddress = findByAddress(opts.trustList, m.authority)
  report.authority = { name: entry?.name ?? null, address: m.authority, network: entry?.network ?? null }
  {
    const reasons: string[] = []
    if (!entry) {
      reasons.push(pinned
        ? `${pinned.name} is trusted on ${pinned.network}, not on ${opts.ledger.network}`
        : sameAddress
          ? `the public key does not match the key pinned for ${sameAddress.name} in the trust list`
          : `authority ${short(m.authority)} is not on the trust list`)
    } else log(`authority ${short(m.authority)} ∈ trust list`)
    let sigOk = false
    try {
      sigOk = pqVerify(pk, canonicalBytes(m), fromHex(sc.manifest_sig), MANIFEST_CTX)
    } catch {
      sigOk = false
    }
    log(`V1 ml_dsa44.verify → ${sigOk}`)
    if (!sigOk) reasons.push('the ML-DSA-44 signature over the manifest is invalid')
    finish('V1', reasons.length ? 'fail' : 'pass', reasons.length ? 'The signature or the signer is not accepted.' : `Valid ML-DSA-44 signature from ${entry!.name}.`, reasons)
  }

  // --- V2 authority anchor ------------------------------------------------------------------
  start('V2')
  let manifestLedger = -1
  try {
    const tx = await opts.ledger.getTx(sc.manifest_tx)
    const problems = anchorProblems(tx, m.authority, MEMO_MANIFEST, manifestMemoData(m, sc.manifest_sig))
    if (tx?.closeTimeIso) report.signedAt = tx.closeTimeIso
    if (tx) manifestLedger = tx.ledgerIndex
    if (!problems.length && entry?.not_after && tx?.closeTimeIso && !(Date.parse(tx.closeTimeIso) < Date.parse(entry.not_after))) {
      problems.push(`signed at ${tx.closeTimeIso}, after the key's not_after ${entry.not_after}`)
    }
    finish('V2', problems.length ? 'fail' : 'pass',
      problems.length ? `Transaction ${short(sc.manifest_tx)} does not match.` : `Recorded in ledger ${tx!.ledgerIndex.toLocaleString('en')}, transaction ${short(sc.manifest_tx)}.`,
      problems.map((p) => `manifest anchor: ${p}`))
  } catch (e) {
    ledgerError('V2', e)
  }

  // --- the hidden set of this copy (V3 display, V5) -----------------------------------------
  let hidden = new Set<number>()
  try {
    hidden = bitmapToSet(d.hidden, grid.n)
  } catch {
    // parseSidecar already validated the bitmap; keep an empty set if not
  }
  report.hiddenLevel = Array.from({ length: grid.n }, (_, i) => (hidden.has(i) ? 1 : -1))
  report.cropped = d.crop && cropFits(grid, d.crop) ? tilesOutsideCrop(grid, d.crop) : []
  report.levels = [{
    index: 1, producer: d.producer, tx: sc.level_tx, ledgerIndex: null, time: null,
    added: [...hidden].sort((a, b) => a - b), hiddenCount: hidden.size, crop: d.crop, recipe: d.recipe,
  }]

  // --- V3 pixels ----------------------------------------------------------------------------
  start('V3')
  let evidence: Image | null = null
  let evidenceOverBudget = false
  try {
    evidence = await readPng(input.evidence, { strict: true, maxPixels })
  } catch (e) {
    evidenceOverBudget = e instanceof OverBudget
    if (e instanceof OverBudget) finish('V3', 'unknown', 'The image is larger than this verifier checks.', [e.message])
    else finish('V3', 'fail', 'The evidence image could not be read.', [(e as Error).message])
  }
  if (evidence) {
    const reasons: string[] = []
    if (evidence.width !== m.w || evidence.height !== m.h) {
      reasons.push(`evidence is ${evidence.width}×${evidence.height}, the manifest says ${m.w}×${m.h}`)
      finish('V3', 'fail', 'The image size does not match the signed size.', reasons)
      evidence = null
    } else {
      const leaves: Uint8Array[] = new Array(grid.n)
      for (const [i, leaf] of sc.hidden) {
        leaves[i] = fromHex(leaf)
        if (!tileIsBlack(evidence, i)) report.badTiles.push(i)
      }
      let doneLeaves = 0
      for (const [i, salt] of sc.visible) {
        leaves[i] = leafHash(i, fromHex(salt), tileBytes(evidence, i))
        if (++doneLeaves % 24 === 0) emit([doneLeaves, sc.visible.length])
      }
      const root = toHex(merkleRoot(leaves))
      report.computedRoot = root
      if (report.badTiles.length) {
        reasons.push(`${report.badTiles.length} hidden tile(s) are not black: ${report.badTiles.slice(0, 6).map((i) => `(${i % grid.cols}, ${Math.floor(i / grid.cols)})`).join(', ')}${report.badTiles.length > 6 ? '…' : ''}`)
      }
      if (root !== m.root) reasons.push('Some visible pixels (or their salts) were changed after signing.')
      finish('V3', reasons.length ? 'fail' : 'pass',
        reasons.length ? 'The pixels are not the ones the authority signed.' : `${sc.visible.length} visible tiles rehashed, ${sc.hidden.length} hidden tiles taken from the sidecar. The root matches.`, reasons)
    }
  }

  // --- V4 level anchor ----------------------------------------------------------------------
  start('V4')
  try {
    // Same order as verify.py: a definite failure is decided before any further ledger call, so a
    // ledger that fails afterwards cannot turn it into "could not verify".
    const reasons: string[] = []
    const info = d.manifest_tx !== sc.manifest_tx ? null : await opts.ledger.getTx(sc.level_tx)
    if (d.manifest_tx !== sc.manifest_tx) reasons.push('the level points to another manifest anchor')
    else reasons.push(...anchorProblems(info, d.producer, MEMO_LEVEL, descriptorHash(d)).map((p) => `level anchor: ${p}`))
    if (info) {
      report.levels[0]!.ledgerIndex = info.ledgerIndex
      report.levels[0]!.time = info.closeTimeIso
    }
    if (info && !reasons.length) {
      if (manifestLedger < 0) manifestLedger = (await opts.ledger.getTx(sc.manifest_tx))?.ledgerIndex ?? -1 // V2 could not tell
      if (manifestLedger < 0) reasons.push('the manifest anchor is not on the ledger')
      else if (info.ledgerIndex < manifestLedger) reasons.push('the level is anchored before the manifest')
    }
    finish('V4', reasons.length ? 'fail' : 'pass',
      reasons.length ? "This copy's record on the ledger does not match the file." : `Published by ${short(d.producer)} in ledger ${info!.ledgerIndex.toLocaleString('en')}.`, reasons)
  } catch (e) {
    ledgerError('V4', e)
  }

  // --- V5 redaction rules -------------------------------------------------------------------
  start('V5')
  {
    const reasons: string[] = []
    if (d.crop && !cropFits(grid, d.crop)) reasons.push('the crop is outside the tile grid')
    else if (d.crop) {
      const shown = tilesOutsideCrop(grid, d.crop).filter((i) => !hidden.has(i))
      if (shown.length) reasons.push(`${shown.length} tile(s) outside the crop are not hidden`)
    }
    try {
      outputSize(m.w, m.h, d.crop, d.recipe)
    } catch (e) {
      reasons.push((e as Error).message)
    }
    const listed = new Set(sc.hidden.map(([i]) => i))
    if (listed.size !== hidden.size || [...hidden].some((i) => !listed.has(i))) reasons.push("the sidecar's hidden list differs from the level's bitmap")
    finish('V5', reasons.length ? 'fail' : 'pass',
      reasons.length ? 'The redaction breaks the rules.' : `${hidden.size}/${grid.n} tiles hidden${report.cropped.length ? `, the crop hides the ${report.cropped.length} tiles outside it` : ''}; crop and recipe valid.`, reasons)
  }

  // --- V6 rendition -------------------------------------------------------------------------
  start('V6')
  if (!input.rendition) {
    finish('V6', 'skipped', 'No published version was provided.')
  } else {
    try {
      const rend = await readPng(input.rendition, { strict: true, maxPixels })
      report.rendition = { width: rend.width, height: rend.height }
      if (evidenceOverBudget) {
        // like velum.verify: the size can still be checked, the pixels cannot
        const [w, h] = outputSize(m.w, m.h, d.crop, d.recipe)
        if (rend.width !== w || rend.height !== h) throw new Error(`recipe gives ${w}×${h}, the rendition is ${rend.width}×${rend.height}`)
        throw new OverBudget('comparing the rendition needs the evidence image, which is above the budget')
      }
      if (!evidence) throw new Error('evidence image unusable (see V3)')
      const expected = applyRecipe(evidence, d.crop, d.recipe)
      const same = expected.width === rend.width && expected.height === rend.height && equal(expected.rgb, rend.rgb)
      finish('V6', same ? 'pass' : 'fail', same ? `Rebuilt from the evidence and identical to the ${rend.width} × ${rend.height} file.` : 'The published version was not made from this evidence.',
        same ? [] : [expected.width !== rend.width || expected.height !== rend.height
          ? `recipe gives ${expected.width}×${expected.height}, the rendition is ${rend.width}×${rend.height}`
          : 'recomputing the recipe from the evidence gives different pixels'])
    } catch (e) {
      if (e instanceof OverBudget) finish('V6', 'unknown', 'The published version is larger than this verifier checks.', [e.message])
      else finish('V6', 'fail', 'The published version could not be read.', [(e as Error).message])
    }
  }

  return done()
}
