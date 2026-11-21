<script setup lang="ts">
/** B — Editor (producer role): open a verified level, redact, crop, set the recipe, export, anchor. */
import { type Crop, type Image, type Recipe, type Rotation, type Sidecar, Grid, applyRecipe, bitmapToSet, parseSidecarText, readPng, readSidecar, tilesOutsideCrop } from '~/lib/velum'
import type { LevelFiles } from '~/composables/useVelum'
import { useLevelFiles } from '~/composables/useLevelFiles'

const level = useLevelFiles()
const verifier = useVerifier('editor')
const step = ref<1 | 2 | 3 | 4>(1)
const phase = ref<'open' | 'verifying' | 'refused' | 'edit' | 'export'>('open')
const parent = shallowRef<{ files: LevelFiles; sidecar: Sidecar; evidence: Image } | null>(null)
const openError = ref<string | null>(null)

async function open(files: LevelFiles) {
  openError.value = null
  if (files.evidence?.name.endsWith('.public.png')) {
    openError.value = 'A redacted copy is made from its evidence image, never from a published version (*.public.png).'
    return
  }
  level.value = files
  phase.value = 'verifying'
  const report = await verifier.run({ evidence: files.evidence!.bytes, sidecar: files.sidecar?.bytes ?? null, rendition: files.rendition?.bytes ?? null, ledger: files.ledger })
  if (!report || report.verdict !== 'verified') {
    phase.value = 'refused'
    return
  }
  // the same sidecar the verifier used: embedded in the PNG first, else the external file
  const text = (await readSidecar(files.evidence!.bytes)) ?? new TextDecoder('ascii').decode(files.sidecar!.bytes)
  const sidecar = parseSidecarText(text)
  const evidence = await readPng(files.evidence!.bytes)
  parent.value = { files, sidecar, evidence }
  resetEdits()
  phase.value = 'edit'
  step.value = 1
}

onMounted(() => {
  if (level.value) open(level.value)
})

// ---- edit state --------------------------------------------------------------------------
const tool = ref<'hide' | 'crop'>('hide')
const pending = ref(new Set<number>())
const crop = ref<Crop | null>(null)
const history = ref<{ pending: Set<number>; crop: Crop | null }[]>([])
const rotate = ref<Rotation>(0)
const outW = ref(0)
const outH = ref(0)
const keepAspect = ref(true)
const brightness = ref(0)
const contrast = ref(0)

const grid = computed(() => (parent.value ? new Grid(parent.value.sidecar.manifest.w, parent.value.sidecar.manifest.h) : null))
const n = computed(() => grid.value?.n ?? 0)
// One sidecar describes one copy (no chain of custody): 1 = the copy opened, 2 = the new one (colours only).
const parentLevel = 1
const newLevel = 2
/** For every tile: 1 if already hidden in the opened copy (it can never be uncovered), -1 if visible. */
const hiddenLevel = computed(() => {
  const p = parent.value
  if (!p) return []
  const hidden = bitmapToSet(p.sidecar.level.hidden, n.value)
  return Array.from({ length: n.value }, (_, i) => (hidden.has(i) ? parentLevel : -1))
})
const outside = computed(() => new Set(grid.value && crop.value ? tilesOutsideCrop(grid.value, crop.value).filter((i) => hiddenLevel.value[i] === -1) : []))
const inherited = computed(() => hiddenLevel.value.filter((k) => k >= 0).length)
const added = computed(() => [...pending.value].filter((i) => hiddenLevel.value[i] === -1 && !outside.value.has(i)).length)
const total = computed(() => inherited.value + added.value + outside.value.size)

/** Size of the image after crop and rotation, before resize: the "no resize" size. */
const baseSize = computed(() => {
  const p = parent.value
  if (!p) return { w: 1, h: 1 }
  let w = p.evidence.width, h = p.evidence.height
  if (crop.value) {
    w = Math.min(crop.value[2] * 64, w - crop.value[0] * 64)
    h = Math.min(crop.value[3] * 64, h - crop.value[1] * 64)
  }
  return rotate.value % 180 ? { w: h, h: w } : { w, h }
})
watch(baseSize, (b) => {
  outW.value = b.w
  outH.value = b.h
}, { immediate: true })
function setW(v: number) {
  outW.value = Math.max(1, Math.min(baseSize.value.w, Math.round(v) || 1))
  if (keepAspect.value) outH.value = Math.max(1, Math.min(baseSize.value.h, Math.round((outW.value * baseSize.value.h) / baseSize.value.w)))
}
function setH(v: number) {
  outH.value = Math.max(1, Math.min(baseSize.value.h, Math.round(v) || 1))
  if (keepAspect.value) outW.value = Math.max(1, Math.min(baseSize.value.w, Math.round((outH.value * baseSize.value.w) / baseSize.value.h)))
}
const recipe = computed<Recipe>(() => ({
  rotate: rotate.value,
  resize: outW.value === baseSize.value.w && outH.value === baseSize.value.h ? null : [outW.value, outH.value],
  brightness: brightness.value,
  contrast: contrast.value,
}))

function resetEdits() {
  pending.value = new Set()
  crop.value = null
  history.value = []
  rotate.value = 0
  brightness.value = 0
  contrast.value = 0
}
function snapshot() {
  history.value = [...history.value.slice(-49), { pending: new Set(pending.value), crop: crop.value }]
}
function paint(tiles: number[], add: boolean) {
  const s = new Set(pending.value)
  for (const t of tiles) add ? s.add(t) : s.delete(t)
  pending.value = s
}
function undo() {
  const h = history.value.at(-1)
  if (!h) return
  pending.value = h.pending
  crop.value = h.crop
  history.value = history.value.slice(0, -1)
}
function clearAdded() {
  snapshot()
  pending.value = new Set()
  crop.value = null
}

// ---- live rendition preview (same velum-js code the verifier runs) -----------------------
const preview = shallowRef<Image | null>(null)
let previewTimer: ReturnType<typeof setTimeout> | undefined
watch([pending, crop, recipe, parent], () => {
  clearTimeout(previewTimer)
  previewTimer = setTimeout(() => {
    const p = parent.value
    if (!p || !grid.value) return
    const rgb = new Uint8Array(p.evidence.rgb)
    const hide = new Set([...pending.value, ...outside.value])
    for (const i of hide) {
      const [x0, y0, w, h] = grid.value.rect(i)
      for (let y = 0; y < h; y++) rgb.fill(0, ((y0 + y) * p.evidence.width + x0) * 3, ((y0 + y) * p.evidence.width + x0 + w) * 3)
    }
    try {
      preview.value = applyRecipe({ width: p.evidence.width, height: p.evidence.height, rgb }, crop.value, recipe.value)
    } catch {
      preview.value = null
    }
  }, 120)
}, { immediate: true, deep: false })

const hidePending = computed(() => [...pending.value].filter((i) => hiddenLevel.value[i] === -1 && !outside.value.has(i)))
const baseName = computed(() => (parent.value?.files.evidence?.name ?? 'copy.png').replace(/\.png$/i, '').replace(/-l\d+$/, ''))
const recipeChanged = computed(() => !!(recipe.value.rotate || recipe.value.resize || recipe.value.brightness || recipe.value.contrast))
const canvasRef = ref<{ hoverText: string } | null>(null)
const barW = (c: number) => `${n.value ? (c / n.value) * 100 : 0}%`
const stepList = [
  { k: 1, label: 'Edit' },
  { k: 2, label: 'Export' },
  { k: 3, label: 'Record' },
  { k: 4, label: 'Check' },
]
</script>

<template>
  <div class="app">
    <AppHeader mode="redact">
      <template v-if="phase === 'edit' || phase === 'export'" #steps>
        <ol aria-label="Steps" class="steps">
          <li v-for="s in stepList" :key="s.k" :class="{ cur: step === s.k }" :aria-current="step === s.k ? 'step' : undefined">
            <span class="sn" :class="{ done: step > s.k }"><VIcon v-if="step > s.k" name="check" :size="11" :stroke="3" /><template v-else>{{ s.k }}</template></span>{{ s.label }}
          </li>
        </ol>
      </template>
      <template v-if="parent && (phase === 'edit' || phase === 'export')" #right>
        <span class="parent-ok">Verified copy opened</span>
      </template>
    </AppHeader>

    <!-- open a level -->
    <ViewerOpen
      v-if="phase === 'open'" title="Redact a level" action="Verify and edit" :error="openError"
      intro="Open a level you received. It has to pass verification before you can black out more of it."
      @open="open"
    >
      <template #aside>
        <div class="card how">
          <h2>Making a new level</h2>
          <ol>
            <li>Click or drag over the image to black out 64-pixel tiles. Tiles already hidden in this copy can't be uncovered.</li>
            <li>Optionally crop. Anything outside the crop is blacked out too.</li>
            <li>Set how the published copy looks: rotation, size, brightness and contrast.</li>
            <li>Record the new level on XRPL. Your wallet extension signs the transaction.</li>
          </ol>
        </div>
      </template>
    </ViewerOpen>

    <!-- verifying the parent -->
    <ViewerVerifying v-else-if="phase === 'verifying' && level" :files="level" :checks="verifier.state.value.checks" :leaves="verifier.state.value.leaves" :log="verifier.state.value.log" @cancel="verifier.cancel(); phase = 'open'" />

    <!-- refused -->
    <main v-else-if="phase === 'refused' && verifier.state.value.report" class="refused">
      <ResultBanner :verdict="verifier.state.value.report.verdict" :checks="verifier.state.value.report.checks" :authority="verifier.state.value.report.authority?.name ?? null" :ms="verifier.state.value.report.ms" @retry="open(level!)" />
      <div class="card ref-note">
        <h2>This level can't be edited</h2>
        <p class="muted">Only levels that pass every check can be redacted further.</p>
        <button type="button" class="btn" @click="phase = 'open'; level = null">Open another level</button>
      </div>
      <ChecksSection title="Checks"><CheckList :checks="verifier.state.value.report.checks" /></ChecksSection>
    </main>

    <!-- edit -->
    <div v-else-if="phase === 'edit' && parent && grid" class="editor">
      <div role="toolbar" aria-label="Tools" class="rail">
        <button type="button" class="tool" :aria-pressed="tool === 'hide'" aria-label="Hide tiles" title="Hide tiles" @click="tool = 'hide'"><VIcon name="hide" :size="20" /></button>
        <button type="button" class="tool" :aria-pressed="tool === 'crop'" aria-label="Crop in whole tiles" title="Crop in whole tiles" @click="tool = 'crop'"><VIcon name="crop" :size="20" /></button>
        <div class="rail-sep" />
        <button type="button" class="tool" aria-label="Undo" title="Undo" :disabled="!history.length" @click="undo"><VIcon name="undo" :size="20" /></button>
        <button type="button" class="tool" aria-label="Clear tiles added at this level" title="Clear this level's edits" @click="clearAdded"><VIcon name="clear" :size="20" /></button>
      </div>

      <section aria-label="Image" class="work">
        <div class="work-bar">
          <span class="mono">{{ parent.files.evidence!.name }}</span>
          <span class="lv small">this copy → new, more redacted copy</span>
          <div class="spacer" />
          <div class="wlegend">
            <span><i class="sw" style="background: #000; box-shadow: inset 0 0 0 2px #8E73FF" />Hidden earlier</span>
            <span><i class="sw" :style="{ background: `repeating-linear-gradient(45deg, ${levelColor(newLevel).stroke} 0 2px, transparent 2px 4px)`, boxShadow: `inset 0 0 0 1.5px ${levelColor(newLevel).stroke}` }" />Hidden by you</span>
            <span><i class="sw" style="background: rgba(18, 19, 46, 0.7); box-shadow: inset 0 0 0 1px #646680" />Outside crop</span>
          </div>
          <button v-if="crop" type="button" class="mini" @click="snapshot(); crop = null">Remove crop</button>
        </div>
        <div class="work-area">
          <div class="work-inner">
            <EditorCanvas
              ref="canvasRef" :bytes="parent.files.evidence!.bytes" :width="parent.evidence.width" :height="parent.evidence.height"
              :tool="tool" :hidden-level="hiddenLevel" :pending="pending" :crop="crop" :outside="outside" :new-level="newLevel"
              @stroke-start="snapshot" @paint="paint" @crop="(c) => (crop = c)"
            />
          </div>
        </div>
        <div class="work-foot">
          <span>{{ tool === 'hide' ? 'Click or drag over tiles to black them out.' : 'Drag over the image to crop it. Everything outside the crop is blacked out.' }}</span>
          <span>{{ canvasRef?.hoverText }}</span>
        </div>
      </section>

      <aside class="panel">
        <div class="pblock">
          <div class="ph"><h2 class="ph-title">Blacked out</h2><span class="display pct">{{ pct(total, n) }}</span></div>
          <div class="bar" aria-hidden="true">
            <div :style="{ width: barW(inherited), background: levelColor(parentLevel || 1).stroke }" />
            <div :style="{ width: barW(added), background: levelColor(newLevel).stroke }" />
            <div :style="{ width: barW(outside.size), background: `repeating-linear-gradient(45deg, ${levelColor(newLevel).stroke} 0 2px, #12132E 2px 4px)` }" />
          </div>
          <dl class="stats">
            <dt><i class="k" :style="{ background: levelColor(parentLevel || 1).stroke }" />Already hidden in this copy</dt><dd>{{ inherited }}</dd>
            <dt><i class="k" :style="{ background: levelColor(newLevel).stroke }" />Hidden by you</dt><dd>{{ added }}</dd>
            <dt><i class="k" :style="{ background: `repeating-linear-gradient(45deg, ${levelColor(newLevel).stroke} 0 2px, #12132E 2px 4px)` }" />Outside the crop</dt><dd>{{ outside.size }}</dd>
            <dt class="tot">Total</dt><dd class="tot">{{ total }} of {{ n }} tiles</dd>
          </dl>
        </div>

        <div class="pblock">
          <h2 class="ph-title">Published version</h2>
          <div class="fld">
            <span class="flabel">Rotate</span>
            <div role="group" aria-label="Rotate" class="seg rot">
              <button v-for="d in [0, 90, 180, 270] as const" :key="d" type="button" class="mono" :aria-pressed="rotate === d" @click="rotate = d">{{ d }}°</button>
            </div>
          </div>
          <div class="size">
            <label class="fld"><span class="flabel">Width</span><input :value="outW" type="number" min="1" :max="baseSize.w" class="field num" @change="setW(+($event.target as HTMLInputElement).value)"></label>
            <span class="x">×</span>
            <label class="fld"><span class="flabel">Height</span><input :value="outH" type="number" min="1" :max="baseSize.h" class="field num" @change="setH(+($event.target as HTMLInputElement).value)"></label>
          </div>
          <label class="check"><input v-model="keepAspect" type="checkbox">Keep proportions (up to {{ baseSize.w }} × {{ baseSize.h }})</label>
          <div class="fld">
            <div class="srow"><label for="ed-b" class="flabel">Brightness</label><span class="sval">{{ brightness > 0 ? '+' : '' }}{{ brightness }}</span></div>
            <input id="ed-b" v-model.number="brightness" type="range" min="-255" max="255">
          </div>
          <div class="fld">
            <div class="srow"><label for="ed-c" class="flabel">Contrast</label><span class="sval">{{ contrast > 0 ? '+' : '' }}{{ contrast }}</span></div>
            <input id="ed-c" v-model.number="contrast" type="range" min="-255" max="255">
          </div>
        </div>

        <div class="pblock">
          <div class="ph"><h2 class="ph-title">Preview</h2><span class="faint small">{{ preview ? `${preview.width} × ${preview.height} px` : '' }}</span></div>
          <PixelCanvas :image="preview" alt="Live preview of the published rendition" />
        </div>

        <div class="pfoot">
          <button type="button" class="btn btn-primary wide" :disabled="added + outside.size === 0 && !recipeChanged" @click="phase = 'export'; step = 2">Export the new copy<VIcon name="arrow" /></button>
          <span class="muted small center">{{ added + outside.size === 0 && !recipeChanged ? 'Hide a tile, crop or change the look to make a new copy.' : 'The tiles you hide are painted black and their salts removed from the sidecar.' }}</span>
        </div>
      </aside>
    </div>

    <!-- export & anchor -->
    <EditorAnchor
      v-else-if="phase === 'export' && parent"
      :parent="parent.sidecar" :evidence="parent.evidence" :pending="[...hidePending]" :crop="crop" :recipe="recipe" :base-name="baseName"
      @back="phase = 'edit'; step = 1" @step-change="(s) => (step = s as 2 | 3 | 4)"
    />
  </div>
</template>

<style scoped>
.app { min-height: 100vh; display: flex; flex-direction: column; }
.steps { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; font-size: 13.5px; }
.steps li { display: inline-flex; align-items: center; gap: 8px; height: 32px; padding: 0 12px 0 6px; border-radius: 16px; color: var(--ink-2); }
.steps li.cur { background: var(--ink); color: var(--paper); font-weight: 600; }
.sn { width: 20px; height: 20px; border-radius: 10px; border: 1px solid var(--line-2); display: inline-flex; align-items: center; justify-content: center; font-family: var(--font-mono); font-size: 11px; }
.steps li.cur .sn { background: var(--mint); color: var(--ink); border: 0; font-weight: 700; }
.sn.done { background: var(--ink); color: var(--mint); border: 0; }
.parent-ok { font-size: 13.5px; color: var(--ok-fg); font-weight: 600; }

.how { padding: 18px 20px; }
.how h2 { margin: 0 0 10px; font-size: 16px; font-weight: 600; }
.how ol { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 8px; font-size: 14px; line-height: 1.5; color: var(--ink-2); }
.how strong { color: var(--ink); font-weight: 600; }

.refused { width: 100%; max-width: 1280px; margin: 0 auto; padding: 28px clamp(16px, 4vw, 40px) 56px; display: flex; flex-direction: column; gap: 20px; }
.ref-note { padding: 20px 22px; display: flex; flex-direction: column; gap: 10px; align-items: flex-start; }
.ref-note h2 { margin: 0; font-size: 18px; font-weight: 600; }
.ref-note p { margin: 0; }

.editor { flex: 1; display: flex; flex-wrap: wrap; align-items: stretch; }
.rail { flex: 0 0 auto; display: flex; flex-direction: column; gap: 6px; padding: 16px 10px; border-right: 1px solid var(--line); background: var(--surface); }
.tool { width: 48px; height: 48px; border-radius: var(--r-md); border: 1px solid transparent; background: transparent; color: var(--ink); display: flex; align-items: center; justify-content: center; cursor: pointer; }
.tool:hover { background: var(--paper-2); }
.tool[aria-pressed='true'] { border: 1.5px solid var(--ink); background: var(--ink); color: var(--paper); }
.tool:disabled { color: var(--line-2); cursor: not-allowed; background: transparent; }
.rail-sep { height: 1px; background: var(--line); margin: 6px 4px; }

.work { flex: 999 1 560px; min-width: 0; display: flex; flex-direction: column; background-color: #1B1C3A; background-image: linear-gradient(rgba(255, 255, 255, 0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(255, 255, 255, 0.04) 1px, transparent 1px); background-size: 32px 32px; color: var(--insp-text); }
.work-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 18px; padding: 14px 24px; border-bottom: 1px solid rgba(255, 255, 255, 0.08); font-size: 13px; }
.lv { display: inline-flex; align-items: center; gap: 6px; color: var(--insp-soft); }
.spacer { flex: 1 1 0; }
.wlegend { display: flex; gap: 14px; flex-wrap: wrap; font-size: 12.5px; color: var(--insp-soft); }
.wlegend span { display: inline-flex; align-items: center; gap: 6px; }
.sw { width: 12px; height: 12px; display: inline-block; }
.mini { height: 30px; padding: 0 10px; border-radius: 6px; border: 1px solid rgba(255, 255, 255, 0.3); background: transparent; color: var(--insp-text); font-size: 12.5px; font-weight: 600; cursor: pointer; }
.work-area { flex: 1; display: flex; align-items: center; justify-content: center; padding: 40px 24px 28px; }
.work-inner { width: 100%; max-width: 900px; }
.work-foot { padding: 12px 24px; border-top: 1px solid rgba(255, 255, 255, 0.08); font-size: 13px; color: var(--insp-soft); display: flex; flex-wrap: wrap; gap: 8px 20px; justify-content: space-between; }

.panel { flex: 1 1 340px; min-width: 0; max-width: 100%; display: flex; flex-direction: column; background: var(--surface); border-left: 1px solid var(--line); }
.pblock { padding: 20px 22px; display: flex; flex-direction: column; gap: 14px; border-bottom: 1px solid var(--paper-2); }
.ph { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
.ph-title { margin: 0; font-size: 15px; font-weight: 600; }
.pct { font-size: 20px; }
.bar { display: flex; height: 10px; border-radius: 3px; overflow: hidden; background: var(--paper-2); }
.stats { margin: 0; display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px 12px; font-size: 14px; }
.stats dt { display: flex; align-items: center; gap: 8px; color: var(--ink-2); }
.stats dd { margin: 0; font-size: 13px; }
.k { width: 10px; height: 10px; display: inline-block; flex: none; }
.tot { font-weight: 600; color: var(--ink) !important; border-top: 1px solid var(--paper-2); padding-top: 8px; }
.fld { display: flex; flex-direction: column; gap: 6px; }
.flabel { font-size: 13px; color: var(--ink-2); }
.rot { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); }
.rot button { font-family: var(--font-mono); font-size: 13px; }
.size { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); gap: 8px; align-items: end; }
.num { height: 40px; }
.x { height: 40px; display: flex; align-items: center; color: var(--ink-3); }
.check { display: flex; align-items: center; gap: 10px; font-size: 13.5px; min-height: 28px; }
.check input { width: 18px; height: 18px; accent-color: var(--ink); }
.srow { display: flex; justify-content: space-between; }
.sval { font-size: 13px; font-weight: 600; }
.small { font-size: 11.5px; }
.pfoot { padding: 20px 22px; margin-top: auto; display: flex; flex-direction: column; gap: 10px; }
.wide { width: 100%; height: 52px; }
.center { text-align: center; font-size: 12.5px; }
</style>
