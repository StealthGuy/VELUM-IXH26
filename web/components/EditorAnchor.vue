<script setup lang="ts">
/**
 * Export & anchor (frontend-spec.md 5, steps 6-8): derive the more redacted copy, check the files,
 * anchor its descriptor with an AccountSet signed by a wallet extension, write the tx hash into the
 * sidecar, embed the sidecar in the evidence PNG (zTXt velum.sidecar), re-verify the exported files.
 * Never asks for, accepts or stores a seed.
 */
import { useSigner, useWallet as useBindingWallet } from '@xrpl-commons/xrpl-connect-vue'
import { isWalletError, WalletErrorCode } from 'xrpl-connect'
import {
  type Crop, type DerivedLevel, type Image, type Recipe, type Sidecar, MEMO_LEVEL, WsLedger,
  canonicalString, deriveLevel, descriptorHash, sha256, sidecarJson, tileIsBlack, toHex, withAnchor, writePng,
} from '~/lib/velum'
import { useLevelFiles } from '~/composables/useLevelFiles'

const props = defineProps<{
  parent: Sidecar
  evidence: Image
  pending: number[]
  crop: Crop | null
  recipe: Recipe | null
  baseName: string
}>()
const emit = defineEmits<{ back: []; stepChange: [step: number] }>()

const { connected, account } = useBindingWallet()
const { signAndSubmit } = useSigner()
const verifier = useVerifier('editor')
const level = useLevelFiles()

const sourceTx = computed(() => props.parent.level_tx)
const producer = computed(() => account.value?.address ?? null)
const wrongNetwork = computed(() => !!account.value && account.value.network.id !== 'testnet')
const name = computed(() => `${props.baseName.replace(/-redacted$/, '')}-redacted`)

type Phase = 'ready' | 'signing' | 'submitted' | 'validated' | 'reverifying' | 'done' | 'error'
const phase = ref<Phase>('ready')
const error = ref<string | null>(null)
const txHash = ref<string | null>(null)
const ledgerIndex = ref<number | null>(null)
const times = reactive<Record<string, string>>({})
const stamp = () => new Date().toLocaleTimeString('en-GB')

/** Derived files for the connected producer. Recomputed only if the producer changes. */
const out = computed(() => {
  if (!producer.value) return null
  const lv: DerivedLevel = deriveLevel({ source: props.parent, evidence: props.evidence, hide: props.pending, crop: props.crop, recipe: props.recipe, producer: producer.value })
  const evidencePng = writePng(lv.evidence)
  const renditionPng = writePng(lv.rendition)
  const descriptorText = canonicalString(lv.descriptor)
  const hidden = lv.draft.hidden.map(([i]) => i)
  const allBlack = hidden.every((i) => tileIsBlack(lv.evidence, i))
  const noSalt = !lv.draft.visible.some(([i]) => hidden.includes(i))
  return { lv, evidencePng, renditionPng, descriptorText, hash: descriptorHash(lv.descriptor), allBlack, noSalt, hiddenCount: hidden.length }
})
const finalSidecar = ref<string | null>(null)
/** The evidence PNG carrying the final sidecar: what gets published and re-verified. */
const finalEvidence = ref<Uint8Array | null>(null)

const files = computed(() => {
  const o = out.value
  if (!o) return []
  const sc = finalSidecar.value ?? sidecarJson({ ...o.lv.draft, level: o.lv.descriptor, level_tx: '0'.repeat(64) } as Sidecar)
  const evidenceSize = finalEvidence.value?.length ?? o.evidencePng.length + sc.length + 25 // zTXt chunk with stored zlib
  return [
    { ext: 'PNG', name: `${name.value}.png`, role: 'Evidence, sidecar embedded', size: evidenceSize, ok: o.allBlack, check: o.allBlack ? `All ${o.hiddenCount} hidden tiles are black` : 'A hidden tile still has pixels', hash: toHex(sha256(o.evidencePng)) },
    { ext: 'JSON', name: `${name.value}.velum.json`, role: 'Sidecar (also a separate file)', size: sc.length, ok: o.noSalt, check: o.noSalt ? `Salts of the ${o.lv.added.length} new hidden tiles removed` : 'A hidden tile still has its salt', hash: finalSidecar.value ? toHex(sha256(new TextEncoder().encode(sc))) : '' },
    { ext: 'PNG', name: `${name.value}.public.png`, role: 'Published version', size: o.renditionPng.length, ok: true, check: `${o.lv.rendition.width} × ${o.lv.rendition.height} px`, hash: toHex(sha256(o.renditionPng)) },
    { ext: 'JSON', name: `${name.value}.descriptor.json`, role: 'Level record', size: o.descriptorText.length, ok: true, check: `Made from copy ${short(sourceTx.value)}`, hash: o.hash },
  ]
})
const checksOk = computed(() => files.value.length > 0 && files.value.every((f) => f.ok))

function findHash(x: unknown, depth = 0): string | null {
  if (!x || typeof x !== 'object' || depth > 5) return null
  for (const [k, v] of Object.entries(x as Record<string, unknown>)) {
    if ((k === 'hash' || k === 'txHash' || k === 'tx_hash') && typeof v === 'string' && /^[0-9A-Fa-f]{64}$/.test(v)) return v.toUpperCase()
  }
  for (const v of Object.values(x as Record<string, unknown>)) {
    const h = findHash(v, depth + 1)
    if (h) return h
  }
  return null
}

async function waitValidated(hash: string) {
  const ledger = new WsLedger()
  try {
    for (let k = 0; k < 30; k++) {
      const tx = await ledger.getTx(hash).catch(() => null)
      if (tx?.validated) {
        if (tx.result !== 'tesSUCCESS') throw new Error(`the ledger rejected the anchor: ${tx.result}`)
        return tx
      }
      await new Promise((r) => setTimeout(r, 1500))
    }
    throw new Error('the anchor was not validated within 45 s; check the explorer and retry')
  } finally {
    ledger.close()
  }
}

async function anchor() {
  const o = out.value
  if (!o || !producer.value || !checksOk.value) return
  error.value = null
  phase.value = 'signing'
  emit('stepChange', 3)
  try {
    const tx = { TransactionType: 'AccountSet', Account: producer.value, Memos: [{ Memo: { MemoType: MEMO_LEVEL.toUpperCase(), MemoData: o.hash.toUpperCase() } }] }
    const res = await signAndSubmit(tx as Parameters<typeof signAndSubmit>[0])
    times.signed = stamp()
    const hash = findHash(res)
    if (!hash) throw new Error('the wallet returned no transaction hash')
    txHash.value = hash
    phase.value = 'submitted'
    times.submitted = stamp()
    const info = await waitValidated(hash)
    ledgerIndex.value = info.ledgerIndex
    phase.value = 'validated'
    times.validated = stamp()
    const sc = withAnchor(o.lv, hash)
    finalSidecar.value = sidecarJson(sc)
    finalEvidence.value = writePng(o.lv.evidence, finalSidecar.value)
    times.written = stamp()
    phase.value = 'reverifying'
    emit('stepChange', 4)
    const report = await verifier.run({ evidence: finalEvidence.value, sidecar: null, rendition: o.renditionPng, ledger: DEFAULT_LEDGER })
    phase.value = report?.verdict === 'verified' ? 'done' : 'error'
    if (report?.verdict !== 'verified') error.value = report?.verdict === 'unknown' ? 'Re-verification could not reach the XRP Ledger. Retry before publishing.' : 'The exported files did not pass every check. Do not publish them.'
  } catch (e) {
    const cancelled = isWalletError(e) && [WalletErrorCode.SIGN_REJECTED, WalletErrorCode.CONNECTION_REJECTED].includes(e.code)
    error.value = cancelled ? 'Signing was cancelled in the wallet.' : (e as Error).message
    phase.value = txHash.value ? 'error' : 'ready'
    if (!txHash.value) emit('stepChange', 2)
  }
}

function downloadAll() {
  const o = out.value
  if (!o || !finalSidecar.value || !finalEvidence.value) return
  downloadBytes(`${name.value}.png`, finalEvidence.value, 'image/png')
  setTimeout(() => downloadBytes(`${name.value}.velum.json`, finalSidecar.value!, 'application/json'), 300)
  setTimeout(() => downloadBytes(`${name.value}.public.png`, o.renditionPng, 'image/png'), 600)
  setTimeout(() => downloadBytes(`${name.value}.descriptor.json`, o.descriptorText, 'application/json'), 900)
}

function openReport() {
  const o = out.value
  if (!o || !finalEvidence.value) return
  level.value = {
    evidence: { name: `${name.value}.png`, bytes: finalEvidence.value },
    sidecar: null,
    rendition: { name: `${name.value}.public.png`, bytes: o.renditionPng },
    source: 'drop', urls: null, ledger: DEFAULT_LEDGER, network: 'testnet',
  }
  useVerifier('viewer').cancel()
  navigateTo('/')
}

const steps = computed(() => [
  { key: 'signed', title: 'Approved in your wallet', detail: 'An AccountSet transaction with one memo', done: !!times.signed, active: phase.value === 'signing' },
  { key: 'submitted', title: 'Sent', detail: 'Submitted to XRPL Testnet', done: !!times.submitted, active: false },
  { key: 'validated', title: 'Confirmed', detail: ledgerIndex.value ? `In ledger ${ledgerIndex.value.toLocaleString('en')}` : 'Waiting for the network to confirm', done: !!times.validated, active: phase.value === 'submitted' },
  { key: 'written', title: 'Saved in the sidecar', detail: 'The transaction hash goes into the sidecar, embedded in the PNG', done: !!times.written, active: false },
])
const descPretty = computed(() => (out.value ? out.value.lv.descriptor : null))
</script>

<template>
  <main class="page">
    <div class="main-col">
      <div class="intro">
        <h1 class="display h1">Export the redacted copy</h1>
      </div>

      <div v-if="!producer" class="card connect">
        <h2>Connect a wallet</h2>
        <p class="muted">The new copy is recorded by your account, and its address is written into the level, so connect first. Use an account on XRPL Testnet.</p>
        <WalletConnector />
      </div>

      <template v-else>
        <div v-if="wrongNetwork" class="card warn"><VIcon name="warn" :size="18" />Your wallet is on {{ account?.network.name }}. Switch it to XRPL Testnet to anchor.</div>
        <div class="card files">
          <div class="fh"><h2>Files</h2></div>
          <div v-for="f in files" :key="f.name" class="file">
            <div class="mono ext">{{ f.ext }}</div>
            <div class="ftxt">
              <div class="fname-row"><span class="mono fname">{{ f.name }}</span><span class="faint small">{{ f.role }}, {{ fmtBytes(f.size) }}</span></div>
              <span class="fcheck" :class="{ bad: !f.ok }"><VIcon :name="f.ok ? 'check' : 'cross'" :size="12" :stroke="2.8" />{{ f.check }}</span>
            </div>
            <span class="mono fhash">{{ f.hash ? short(f.hash) : '' }}</span>
          </div>
        </div>

        <div v-if="descPretty && out" class="card desc">
          <h2>Level record</h2>
          <p class="muted">This is what goes on the ledger, as a hash in the transaction memo.</p>
          <dl class="ddl">
            <dt>Made from</dt><dd class="mono">{{ short(sourceTx) }}</dd>
            <dt>Recorded by</dt><dd class="mono">{{ short(descPretty.producer) }}</dd>
            <dt>Hidden tiles</dt><dd>{{ out.hiddenCount }}</dd>
            <template v-for="row in recipeRows(descPretty.crop, descPretty.recipe)" :key="row[0]"><dt>{{ row[0] }}</dt><dd>{{ row[1] }}</dd></template>
            <dt>Hash</dt><dd class="mono">{{ hashGroups(out.hash) }}</dd>
          </dl>
        </div>
        <button type="button" class="btn-quiet btn btn-sm back" :disabled="phase !== 'ready'" @click="$emit('back')">Back to editing</button>
      </template>
    </div>

    <aside class="side">
      <div class="card-stamp anchor">
        <div class="ah">
          <h2 class="display">Record on XRPL</h2>
          <span class="wtag">{{ producer ? short(producer) : 'No wallet' }}</span>
        </div>
        <dl class="dl">
          <dt>Type</dt><dd class="mono">AccountSet</dd>
          <dt>Account</dt><dd class="mono">{{ producer ? short(producer) : '—' }}</dd>
          <dt>Memo type</dt><dd class="mono">velum/level</dd>
          <dt>Memo</dt><dd class="mono">{{ out ? hashGroups(out.hash) : '—' }}</dd>
        </dl>
        <ol class="steps">
          <li v-for="s in steps" :key="s.key">
            <span class="sdot" :class="{ done: s.done, active: s.active }"><VIcon v-if="s.done" name="check" :size="12" :stroke="3" /><VIcon v-else-if="s.active" name="spin" :size="14" /></span>
            <div class="stxt"><span class="stitle">{{ s.title }}</span><span class="sdetail">{{ s.detail }}</span></div>
            <span class="mono stime">{{ times[s.key] ?? '' }}</span>
          </li>
        </ol>
        <div class="afoot">
          <a v-if="txHash" :href="explorerTx(txHash, 'testnet')!" target="_blank" rel="noopener" class="txl">View transaction ↗</a>
          <button v-if="phase === 'ready' || (phase === 'error' && !txHash)" type="button" class="btn btn-primary wide" :disabled="!producer || wrongNetwork || !checksOk" @click="anchor">Sign and record</button>
          <p v-if="error" class="err"><VIcon name="warn" :size="14" />{{ error }}</p>
        </div>
      </div>

      <div v-if="phase === 'reverifying'" class="card rv-run"><VIcon name="spin" :size="18" style="color: var(--signal)" /><span>Checking the exported files ({{ verifier.state.value.checks.filter((c) => c.state === 'pass').length }} of 6)</span></div>
      <div v-if="phase === 'done'" class="rv-ok">
        <div class="rv-head"><span class="display rv-title">Verified</span><button type="button" class="btn-quiet btn btn-sm rv-link" @click="openReport">Open report</button></div>
        <span class="rv-text">The exported files pass every check, including the new ledger record.</span>
        <button type="button" class="btn btn-primary wide rv-dl" @click="downloadAll"><VIcon name="download" />Download the files</button>
      </div>
      <ChecksSection v-if="phase === 'error' && verifier.state.value.report" title="Checks"><CheckList :checks="verifier.state.value.checks" /></ChecksSection>

      <div class="seed-note">
        <div class="sn-ic"><VIcon name="lock" :size="16" :stroke="1.7" /></div>
        <span>Your wallet extension signs the transaction. This page never sees your seed or keys.</span>
      </div>
    </aside>
  </main>
</template>

<style scoped>
.page { width: 100%; max-width: 1280px; margin: 0 auto; padding: 32px clamp(16px, 4vw, 40px) 56px; display: flex; flex-wrap: wrap; gap: 28px; align-items: flex-start; }
.main-col { flex: 999 1 560px; min-width: 0; display: flex; flex-direction: column; gap: 20px; }
.side { flex: 1 1 380px; min-width: 0; display: flex; flex-direction: column; gap: 16px; }
.intro { display: flex; flex-direction: column; gap: 10px; }
.h1 { margin: 0; font-size: clamp(28px, 3.4vw, 42px); line-height: 1.02; }
.small { font-size: 12.5px; }
.connect { padding: 22px; display: flex; flex-direction: column; gap: 12px; align-items: flex-start; }
.connect h2 { margin: 0; font-size: 18px; font-weight: 600; }
.connect p { margin: 0; font-size: 14.5px; line-height: 1.5; }
.warn { padding: 14px 18px; display: flex; gap: 10px; align-items: center; background: var(--warn-bg); color: var(--warn-fg); border-color: var(--warn-mark); font-weight: 600; font-size: 14px; }
.files { overflow: hidden; }
.fh { padding: 16px 20px; display: flex; justify-content: space-between; align-items: baseline; border-bottom: 1px solid var(--paper-2); }
.fh h2 { margin: 0; font-size: 16px; font-weight: 600; }
.file { display: grid; grid-template-columns: 40px minmax(0, 1fr) auto; gap: 14px; align-items: center; padding: 14px 20px; border-bottom: 1px solid var(--paper-2); }
.file:last-child { border-bottom: 0; }
.ext { width: 40px; height: 40px; border-radius: var(--r-md); background: var(--paper); border: 1px solid var(--line); display: flex; align-items: center; justify-content: center; font-size: 10.5px; font-weight: 600; color: var(--ink-2); }
.ftxt { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.fname-row { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
.fname { font-size: 13.5px; font-weight: 600; }
.fcheck { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: var(--ok-fg); }
.fcheck svg { color: var(--ok-mark); }
.fcheck.bad, .fcheck.bad svg { color: var(--bad-fg); }
.fhash { font-size: 12px; color: var(--ink-2); }
.desc { padding: 18px 20px; display: flex; flex-direction: column; gap: 8px; }
.desc h2 { margin: 0; font-size: 16px; font-weight: 600; }
.desc p { margin: 0; font-size: 14px; }
.ddl { margin: 6px 0 0; display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 8px 16px; font-size: 14px; }
.ddl dt { color: var(--ink-2); }
.ddl dd { margin: 0; text-align: right; }
.back { align-self: flex-start; }

.anchor { overflow: hidden; }
.ah { padding: 18px 20px; border-bottom: 1px solid var(--paper-2); display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.ah h2 { margin: 0; font-size: 18px; }
.wtag { display: inline-flex; align-items: center; height: 30px; padding: 0 10px; border-radius: 6px; background: var(--paper-2); font-size: 13px; font-weight: 600; }
.dl { margin: 0; padding: 16px 20px; display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 10px 16px; font-size: 13.5px; border-bottom: 1px solid var(--paper-2); }
.dl dt { color: var(--ink-2); }
.dl dd { margin: 0; text-align: right; font-size: 13px; }
.steps { list-style: none; margin: 0; padding: 16px 20px 4px; display: flex; flex-direction: column; }
.steps li { display: grid; grid-template-columns: 24px minmax(0, 1fr) auto; gap: 12px; align-items: start; padding: 8px 0; }
.sdot { width: 24px; height: 24px; border-radius: 12px; border: 1px solid var(--line-2); display: inline-flex; align-items: center; justify-content: center; }
.sdot.done { background: var(--ink); color: var(--mint); border-color: var(--ink); }
.sdot.active { border-color: var(--signal); color: var(--signal); }
.stxt { display: flex; flex-direction: column; gap: 2px; }
.stitle { font-size: 14.5px; font-weight: 600; }
.sdetail { font-size: 13px; color: var(--ink-2); }
.stime { font-size: 12px; color: var(--ink-3); }
.afoot { padding: 4px 20px 18px; display: flex; flex-direction: column; gap: 12px; }
.txl { font-size: 13px; font-weight: 600; }
.wide { width: 100%; height: 52px; }
.err { margin: 0; display: flex; gap: 8px; align-items: flex-start; font-size: 13.5px; color: var(--bad-fg); }
.rv-run { padding: 16px 20px; display: flex; gap: 12px; align-items: center; font-weight: 600; font-size: 14px; }
.rv-ok { background: var(--ok-bg); border: 1.5px solid var(--ink); border-radius: var(--r-lg); padding: 16px 20px; display: flex; flex-direction: column; gap: 12px; }
.rv-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.rv-title { font-size: 16px; color: var(--ok-fg); }
.rv-link { color: var(--ok-fg); }
.rv-text { font-size: 14px; color: var(--ok-fg); }
.rv-dl { box-shadow: 0 4px 0 var(--ok-fg); }
.seed-note { background: var(--ink); color: var(--insp-soft); border-radius: var(--r-lg); padding: 16px 18px; display: flex; gap: 14px; align-items: flex-start; font-size: 13.5px; line-height: 1.5; }
.sn-ic { width: 36px; height: 36px; flex: none; border-radius: var(--r-md); background: var(--lemon); color: var(--ink); display: flex; align-items: center; justify-content: center; }
</style>
