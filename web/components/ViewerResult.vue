<script setup lang="ts">
import { Grid, type LevelInfo, type Report, sha256, tilesOutsideCrop, toHex } from '~/lib/velum'
import type { LevelFiles } from '~/composables/useVelum'

const props = defineProps<{ report: Report; files: LevelFiles }>()
defineEmits<{ retry: []; edit: []; reset: [] }>()

const r = computed(() => props.report)
const n = computed(() => r.value.cols * r.value.rows)
/** The copy this file describes (a sidecar carries one level, no chain of custody). */
const copy = computed(() => r.value.levels[0] ?? null)
const hiddenTotal = computed(() => r.value.hiddenLevel.filter((k) => k >= 0).length)
const hasRendition = computed(() => !!props.files.rendition && !!r.value.rendition)
const view = ref<'evidence' | 'rendition'>('evidence')
const mask = ref(true)
const rejected = computed(() => r.value.verdict === 'rejected')
const failed = computed(() => r.value.checks.filter((c) => c.state === 'fail'))
const passed = computed(() => r.value.checks.filter((c) => c.state === 'pass'))
const net = computed(() => props.files.network)
const authorityName = computed(() => r.value.authority?.name ?? null)
const copied = ref(false)

const croppedCount = computed(() => r.value.cropped.length)
const legend = computed(() => {
  const out: { k: number; text: string; kind: 'tile' | 'crop' }[] = []
  const l = copy.value
  if (!l) return out
  if (hiddenTotal.value - croppedCount.value > 0) out.push({ k: l.index, text: 'Blacked out', kind: 'tile' })
  if (croppedCount.value) out.push({ k: l.index, text: 'Outside the crop', kind: 'crop' })
  return out
})

const whatItMeans = computed(() => {
  const ids = failed.value.map((c) => c.id)
  const others = (['V1', 'V2', 'V4', 'V5'] as const).every((id) => r.value.checks.find((c) => c.id === id)?.state === 'pass')
  if (ids.includes('V3') && others) return "The signature and the ledger records check out, but the image was edited after it was signed. Don't rely on it as evidence."
  if (ids.includes('V1')) return "No authority on the trust list vouches for this image, so there's no way to tell whether it's genuine."
  if (ids.includes('V2') || ids.includes('V4')) return "The file points to ledger records that don't exist or don't match, so who published this copy can't be trusted."
  if (ids.includes('V5')) return "This copy keeps pixels outside its crop, uses settings that can't be applied, or its hidden tiles differ from its ledger record."
  if (ids.includes('V6')) return "The evidence may be genuine, but the published version wasn't produced from it with the stated settings."
  return 'At least one check failed. Treat the image as unverified.'
})

const failText: Record<string, string> = {
  V1: 'Signature not accepted',
  V2: "Authority's ledger record doesn't match",
  V3: "Pixels don't match the signature",
  V4: "This copy's ledger record doesn't match",
  V5: 'Redaction rules broken',
  V6: "Published version doesn't match",
}

function outsideFor(l: LevelInfo) {
  return l.crop ? tilesOutsideCrop(new Grid(r.value.width, r.value.height), l.crop) : []
}

function producerName(addr: string) {
  return r.value.manifest && addr === r.value.manifest.authority ? authorityName.value : null
}

const shareLink = computed(() => {
  const u = props.files.urls
  if (!u) return null
  const q = new URLSearchParams({ evidence: u.evidence })
  if (u.sidecar) q.set('sidecar', u.sidecar)
  if (u.rendition) q.set('rendition', u.rendition)
  return `${location.origin}/?${q}`
})
async function copyLink() {
  if (!shareLink.value) return
  await copyText(shareLink.value)
  copied.value = true
  setTimeout(() => (copied.value = false), 1500)
}

const baseName = computed(() => (props.files.evidence?.name ?? 'copy.png').replace(/\.png$/i, ''))
function reportJson() {
  const f = props.files
  const fileInfo = (x: { name: string; bytes: Uint8Array } | null) => (x ? { name: x.name, bytes: x.bytes.length, sha256: toHex(sha256(x.bytes)) } : null)
  return JSON.stringify({
    velum_report: 1,
    generated: new Date().toISOString(),
    verifier: 'velum-js 0.1 (browser)',
    trust_list: TRUST_LIST.version,
    ledger: r.value.ledger,
    files: { evidence: fileInfo(f.evidence), sidecar: fileInfo(f.sidecar), rendition: fileInfo(f.rendition) },
    sidecar_source: r.value.sidecarSource,
    verdict: r.value.verdict,
    checks: r.value.checks.map(({ id, title, state, detail, reasons }) => ({ id, title, state, detail, reasons })),
    authority: r.value.authority,
    signed_at: r.value.signedAt,
    image: { w: r.value.width, h: r.value.height, tiles: n.value, hidden: hiddenTotal.value },
    level: copy.value && { producer: copy.value.producer, tx: copy.value.tx, ledger_index: copy.value.ledgerIndex, time: copy.value.time, tiles_hidden: copy.value.hiddenCount },
    computed_root: r.value.computedRoot,
  }, null, 2)
}
const downloads = computed(() => {
  const f = props.files
  const out: { name: string; role: string; size: number; get: () => void }[] = []
  if (f.evidence) out.push({ name: f.evidence.name, role: 'Evidence', size: f.evidence.bytes.length, get: () => downloadBytes(f.evidence!.name, f.evidence!.bytes, 'image/png') })
  if (f.sidecar) out.push({ name: f.sidecar.name, role: 'Sidecar', size: f.sidecar.bytes.length, get: () => downloadBytes(f.sidecar!.name, f.sidecar!.bytes, 'application/json') })
  if (f.rendition) out.push({ name: f.rendition.name, role: 'Published', size: f.rendition.bytes.length, get: () => downloadBytes(f.rendition!.name, f.rendition!.bytes, 'image/png') })
  return out
})
const saveReport = () => downloadBytes(`${baseName.value}.report.json`, reportJson(), 'application/json')

const frame = computed(() => (view.value === 'rendition' && hasRendition.value
  ? { bytes: props.files.rendition!.bytes, w: r.value.rendition!.width, h: r.value.rendition!.height }
  : { bytes: props.files.evidence!.bytes, w: r.value.width, h: r.value.height }))
const caption = computed(() => (view.value === 'rendition' && hasRendition.value
  ? `${props.files.rendition!.name}, ${frame.value.w} × ${frame.value.h}`
  : `${props.files.evidence!.name}, ${r.value.width} × ${r.value.height}`))
const caption2 = computed(() => {
  if (rejected.value) return r.value.badTiles.length ? `${r.value.badTiles.length} hidden tiles still have pixels` : ''
  if (view.value === 'rendition') return 'Switch to the evidence to see the mask.'
  return ''
})
const maskLabel = computed(() => `Redaction mask: ${hiddenTotal.value} of ${n.value} tiles hidden`)
const sidecarText = computed(() => (r.value.sidecarSource === 'embedded' ? 'Embedded in the PNG' : r.value.sidecarSource === 'external' ? 'Separate .velum.json file' : '—'))
</script>

<template>
  <main class="page">
    <ResultBanner :verdict="r.verdict" :checks="r.checks" :authority="authorityName" :ms="r.ms" :error="r.error" @retry="$emit('retry')">
      <template #actions>
        <button type="button" class="btn btn-md" @click="saveReport"><VIcon name="download" />Report.json</button>
        <button v-if="shareLink" type="button" class="btn btn-md btn-primary" style="box-shadow: 0 3px 0 var(--signal)" @click="copyLink">{{ copied ? 'Copied' : 'Copy link' }}</button>
        <button v-else type="button" class="btn btn-md" @click="$emit('reset')">Verify another</button>
      </template>
    </ResultBanner>

    <!-- image + facts -->
    <section class="cols">
      <div class="img-col">
        <div class="toolbar">
          <div v-if="hasRendition" role="group" aria-label="Image" class="seg">
            <button type="button" :aria-pressed="view === 'rendition'" @click="view = 'rendition'">Rendition</button>
            <button type="button" :aria-pressed="view === 'evidence'" @click="view = 'evidence'">Evidence</button>
          </div>
          <button v-if="!rejected" type="button" class="toggle" :aria-pressed="mask" :disabled="view !== 'evidence'" @click="mask = !mask">
            <span class="knob" :class="{ on: mask }"><span /></span>Redaction mask
          </button>
          <div class="spacer" />
          <div v-if="!rejected && view === 'evidence' && mask" class="legend">
            <span v-for="l in legend" :key="l.text"><i class="sw" :style="l.kind === 'crop' ? { background: `repeating-linear-gradient(45deg, ${levelColor(l.k).stroke} 0 2px, #12132E 2px 5px)` } : { background: '#12132E', boxShadow: `inset 0 0 0 2.5px ${levelColor(l.k).stroke}` }" />{{ l.text }}</span>
          </div>
        </div>
        <ImageFrame :bytes="frame.bytes" :width="frame.w" :height="frame.h" :dim="rejected" :alt="caption">
          <TileMask v-if="rejected && view === 'evidence'" :width="r.width" :height="r.height" mode="reject" :bad-tiles="r.badTiles" label="Hidden tiles that are not black" />
          <TileMask v-else-if="view === 'evidence' && mask" :width="r.width" :height="r.height" mode="mask" grid :hidden-level="r.hiddenLevel" :crop-outside="r.cropped" :label="maskLabel" />
        </ImageFrame>
        <div class="captions"><span>{{ caption }}</span><span>{{ caption2 }}</span></div>
      </div>

      <aside class="side">
        <!-- rejected: what failed -->
        <template v-if="rejected">
          <div class="card fail-card">
            <div class="fail-head"><h2>What failed</h2></div>
            <div v-for="c in failed" :key="c.id" class="fail-item">
              <div class="fail-title"><span class="fid">{{ c.id }}</span><span>{{ failText[c.id] }}</span></div>
              <ul class="fail-reasons"><li v-for="(x, k) in c.reasons" :key="k">{{ sentence(x) }}</li></ul>
              <dl v-if="c.id === 'V3' && r.computedRoot && r.manifest && r.computedRoot !== r.manifest.root" class="roots">
                <dt>From these pixels</dt><dd class="mono bad-h">{{ hashGroups(r.computedRoot) }}</dd>
                <dt>Signed</dt><dd class="mono">{{ hashGroups(r.manifest.root) }}</dd>
              </dl>
            </div>
          </div>
          <div class="card pad">
            <h2 class="h2s">What this means</h2>
            <p class="p">{{ whatItMeans }}</p>
          </div>
          <ChecksSection v-if="passed.length" title="Checks that passed">
            <div class="passed">
              <div v-for="c in passed" :key="c.id" class="passed-row"><VIcon name="check" :size="14" style="color: var(--ok-mark)" /><span>{{ c.title }}</span></div>
            </div>
          </ChecksSection>
        </template>

        <!-- facts -->
        <div v-else class="card facts">
          <div class="fact-block">
            <span class="label">Signed by</span>
            <div class="party">
              <div class="display pbadge">L0</div>
              <div class="ptxt">
                <div class="pname-row">
                  <span v-if="authorityName" class="pname">{{ authorityName }}</span>
                  <span v-else class="pname">Not on the trust list</span>
                  <span v-if="authorityName" class="trust-tag">On the trust list</span>
                </div>
                <span class="mono paddr">{{ r.authority ? short(r.authority.address) : '—' }}</span>
              </div>
            </div>
          </div>
          <dl class="dl">
            <dt>Signed on</dt><dd>{{ fmtDate(r.signedAt) }}</dd>
            <dt>Size</dt><dd>{{ r.width }} × {{ r.height }} px</dd>
            <dt>Redactions</dt><dd>{{ hiddenTotal === 0 ? 'None' : `${hiddenTotal} tiles` }}</dd>
            <dt>Sidecar</dt><dd>{{ sidecarText }}</dd>
            <dt>Signature</dt><dd>ML-DSA-44</dd>
          </dl>
          <div class="hidden-block">
            <div class="hb-top"><span class="muted">Blacked out</span><span class="display hb-pct">{{ pct(hiddenTotal, n) }}</span></div>
            <div class="bar" aria-hidden="true">
              <div v-if="copy" :style="{ width: `${(hiddenTotal / n) * 100}%`, background: levelColor(copy.index).stroke }" />
            </div>
            <div class="hb-foot"><span>{{ hiddenTotal ? `${hiddenTotal - croppedCount} blacked out${croppedCount ? `, ${croppedCount} outside the crop` : ''}` : 'Nothing hidden' }}</span><span>{{ hiddenTotal }} of {{ n }} tiles</span></div>
          </div>
          <HashField v-if="r.manifest" label="Merkle root" :value="r.manifest.root" />
          <div class="recipe">
            <span class="label">Published version</span>
            <dl class="dl recipe-dl">
              <template v-for="row in recipeRows(copy?.crop ?? null, copy?.recipe ?? null)" :key="row[0]"><dt>{{ row[0] }}</dt><dd>{{ row[1] }}</dd></template>
            </dl>
          </div>
        </div>
        <button v-if="r.verdict === 'verified'" type="button" class="btn editor-btn" @click="$emit('edit')">Redact further in the Editor</button>
      </aside>
    </section>

    <!-- this copy: who published it, and where on the ledger -->
    <section v-if="copy" class="chain-sec">
      <div class="sec-head">
        <h2 class="display h2">This copy</h2>
      </div>
      <ol class="chain">
        <li class="node current">
          <div class="node-top"><span class="nt-left"><span class="nt-name">Published from the signed image</span></span><span class="muted small">{{ fmtShortDate(copy.time) }}</span></div>
          <ImageFrame :bytes="files.evidence!.bytes" :width="r.width" :height="r.height" plain alt="This copy">
            <TileMask :width="r.width" :height="r.height" mode="thumb" :hidden-level="r.hiddenLevel" :upto-level="copy.index" :crop-outside="outsideFor(copy)" :label="`${copy.hiddenCount} tiles hidden`" />
          </ImageFrame>
          <div class="node-who">
            <template v-if="producerName(copy.producer)"><span class="nw-name">{{ producerName(copy.producer) }}</span><span class="nw-sub"><span class="mono">{{ short(copy.producer) }}</span>, the authority's account</span></template>
            <template v-else><span class="mono nw-addr">{{ short(copy.producer) }}</span><span class="nw-sub2">An account not on the trust list: it can only add black</span></template>
          </div>
          <div class="node-foot">
            <span>{{ copy.hiddenCount ? `${copy.hiddenCount} tiles hidden${copy.crop ? ', cropped' : ''}` : 'Nothing hidden' }}</span>
            <a v-if="explorerTx(copy.tx, net)" :href="explorerTx(copy.tx, net)!" target="_blank" rel="noopener" class="txl">Transaction ↗</a>
            <span v-else class="mono faint">{{ short(copy.tx) }}</span>
          </div>
        </li>
      </ol>
    </section>

    <!-- checks + downloads -->
    <section class="cols">
      <div class="checks-col">
        <ChecksSection title="Checks">
          <CheckList :checks="r.checks" show-ms />
        </ChecksSection>
      </div>
      <div class="side">
        <div class="card dls">
          <h2>Downloads</h2>
          <button v-for="d in downloads" :key="d.name" type="button" class="dl-row" @click="d.get()"><span class="mono">{{ d.name }}</span><span class="muted small">{{ d.role }}, {{ fmtBytes(d.size) }}</span></button>
          <button type="button" class="dl-row" @click="saveReport"><span class="mono">{{ baseName }}.report.json</span><span class="muted small">Verification report</span></button>
        </div>
      </div>
    </section>
  </main>
</template>

<style scoped>
.page { width: 100%; max-width: 1280px; margin: 0 auto; padding: 28px clamp(16px, 4vw, 40px) 64px; display: flex; flex-direction: column; gap: 28px; }
.cols { display: flex; flex-wrap: wrap; gap: 24px; align-items: flex-start; }
.img-col, .checks-col { flex: 999 1 600px; min-width: 0; display: flex; flex-direction: column; gap: 12px; }
.side { flex: 1 1 320px; min-width: 0; display: flex; flex-direction: column; gap: 16px; }
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }
.spacer { flex: 1 1 0; }
.toggle { height: 44px; padding: 0 14px 0 8px; border-radius: var(--r-md); border: 1px solid var(--line); background: var(--surface); color: var(--ink); font-size: 14px; font-weight: 600; display: inline-flex; align-items: center; gap: 10px; cursor: pointer; }
.toggle:disabled { color: var(--ink-3); cursor: not-allowed; }
.knob { width: 36px; height: 22px; border-radius: 11px; background: var(--line); display: inline-flex; align-items: center; padding: 3px; justify-content: flex-start; }
.knob span { width: 16px; height: 16px; border-radius: 8px; background: #fff; }
.knob.on { background: var(--ink); justify-content: flex-end; }
.knob.on span { background: var(--mint); }
.legend { display: flex; gap: 14px; flex-wrap: wrap; font-size: 13px; color: var(--ink-2); }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.sw { width: 14px; height: 14px; display: inline-block; }
.captions { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px; font-size: 12.5px; color: var(--ink-2); }

.facts { padding: 20px; display: flex; flex-direction: column; gap: 18px; }
.fact-block { display: flex; flex-direction: column; gap: 8px; }
.party { display: flex; gap: 12px; align-items: center; }
.pbadge { width: 44px; height: 44px; border-radius: var(--r-md); background: var(--ink); color: var(--paper); display: flex; align-items: center; justify-content: center; font-size: 13px; flex: none; }
.ptxt { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.pname-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.pname { font-size: 16px; font-weight: 600; }
.trust-tag { font-size: 12px; font-weight: 600; background: var(--lilac); padding: 2px 7px; border-radius: var(--r-sm); }
.paddr { font-size: 13px; color: var(--ink-2); }
.dl { margin: 0; display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 12px 16px; font-size: 14px; border-top: 1px solid var(--paper-2); padding-top: 16px; }
.dl dt { color: var(--ink-2); }
.dl dd { margin: 0; text-align: right; font-weight: 600; }
.dl dd.mono { font-weight: 400; font-size: 13px; }
.hidden-block { display: flex; flex-direction: column; gap: 8px; border-top: 1px solid var(--paper-2); padding-top: 16px; }
.hb-top { display: flex; justify-content: space-between; align-items: baseline; font-size: 14px; }
.hb-pct { font-size: 22px; }
.bar { display: flex; height: 10px; border-radius: 3px; overflow: hidden; background: var(--paper-2); }
.hb-foot { display: flex; justify-content: space-between; font-size: 12px; color: var(--ink-2); gap: 8px; }
.facts :deep(.hf) { border-top: 1px solid var(--paper-2); padding-top: 16px; }
.recipe { display: flex; flex-direction: column; gap: 6px; }
.recipe-txt { font-size: 12.5px; line-height: 1.6; }
.editor-btn { width: 100%; }

.fail-card { border: 1.5px solid var(--bad-mark); overflow: hidden; }
.fail-head { padding: 14px 20px; background: #FFF7F3; border-bottom: 1px solid var(--bad-bg); }
.fail-head h2 { margin: 0; font-size: 16px; font-weight: 600; color: var(--bad-fg); }
.fail-item { padding: 18px 20px; display: flex; flex-direction: column; gap: 10px; border-bottom: 1px solid var(--paper-2); }
.fail-item:last-child { border-bottom: 0; }
.fail-title { display: flex; align-items: center; gap: 10px; font-size: 15px; font-weight: 600; }
.fid { font-size: 13px; font-weight: 700; color: var(--bad-fg); }
.nt-left { display: inline-flex; align-items: center; gap: 8px; }
.nt-name { font-size: 14px; font-weight: 600; }
.legend-later { display: inline-flex; align-items: center; gap: 6px; }
.recipe-dl { border-top: 0; padding-top: 0; font-size: 13.5px; gap: 6px 16px; }
.fail-reasons { margin: 0; padding-left: 18px; font-size: 14px; line-height: 1.5; color: var(--ink-2); }
.roots { margin: 0; display: grid; grid-template-columns: 1fr; gap: 4px 12px; font-size: 13px; background: var(--paper); border-radius: 6px; padding: 10px 12px; }
.roots dt { color: var(--ink-2); }
.roots dd { margin: 0 0 6px; }
.bad-h { color: var(--bad-fg); }
.pad { padding: 18px 20px; display: flex; flex-direction: column; gap: 8px; }
.h2s { margin: 0; font-size: 15px; font-weight: 600; }
.p { margin: 0; font-size: 14px; line-height: 1.55; color: var(--ink-2); }
.passed { padding: 4px 20px 6px; }
.passed-h { margin-bottom: 4px; }
.passed-row { display: grid; grid-template-columns: 24px minmax(0, 1fr); align-items: center; gap: 10px; min-height: 44px; border-bottom: 1px solid var(--paper-2); font-size: 14px; }
.passed-row:last-child { border-bottom: 0; }
.fid2 { font-size: 13px; font-weight: 600; }

.chain-sec { display: flex; flex-direction: column; gap: 16px; }
.sec-head { display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 8px; }
.h2 { margin: 0; font-size: 24px; }
.small { font-size: 13.5px; }
.chain { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(280px, 100%), 1fr)); }
.node { display: flex; flex-direction: column; gap: 14px; padding: 20px; background: var(--surface); border: 1px solid var(--line); border-left-width: 0; }
.node:first-child { border-left-width: 1px; border-radius: 12px 0 0 12px; }
.node:last-child { border-radius: 0 12px 12px 0; }
.node:only-child { border-radius: 12px; }
.node.current { border: 1.5px solid var(--ink); box-shadow: var(--stamp); position: relative; z-index: 1; }
.node-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.node-who { display: flex; flex-direction: column; gap: 2px; }
.nw-name { font-size: 15px; font-weight: 600; }
.nw-addr { font-size: 14px; font-weight: 600; }
.nw-sub { font-size: 12.5px; color: var(--ink-2); }
.nw-sub2 { font-size: 12.5px; color: var(--ink-2); }
.node-foot { display: flex; justify-content: space-between; align-items: center; border-top: 1px solid var(--paper-2); padding-top: 12px; font-size: 12.5px; }
.txl { font-weight: 600; font-size: 12.5px; }

.checks-card { overflow: hidden; }
.cc-head { padding: 16px 20px; display: flex; justify-content: space-between; align-items: baseline; border-bottom: 1px solid var(--paper-2); gap: 8px; flex-wrap: wrap; }
.cc-head h2 { margin: 0; font-size: 16px; font-weight: 600; }
.cc-head .mono { font-size: 12px; }
.dls { padding: 18px 20px; display: flex; flex-direction: column; }
.dls h2 { margin: 0 0 8px; font-size: 16px; font-weight: 600; }
.dl-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; min-height: 44px; border: 0; border-bottom: 1px solid var(--paper-2); background: transparent; color: var(--ink); cursor: pointer; text-align: left; padding: 0; }
.dl-row:last-child { border-bottom: 0; }
.dl-row:hover .mono { color: var(--signal); text-decoration: underline; }
.dl-row .mono { font-size: 13px; overflow: hidden; text-overflow: ellipsis; }
.manifest { padding: 18px 20px; display: flex; flex-direction: column; gap: 4px; font-size: 12.5px; line-height: 1.6; }
.m-label { font-family: var(--font-text); color: var(--insp-soft); margin-bottom: 6px; }
.ind { padding-left: 16px; }
</style>
