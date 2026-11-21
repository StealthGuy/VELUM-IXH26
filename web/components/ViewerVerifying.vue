<script setup lang="ts">
import { type Check, readSidecar } from '~/lib/velum'
import type { LevelFiles } from '~/composables/useVelum'

const props = defineProps<{ files: LevelFiles; checks: Check[]; leaves: [number, number] | null; log: string[] }>()
defineEmits<{ cancel: [] }>()

/** Peek at the sidecar (embedded first) on the main thread for the picture only; the worker does the real parsing. */
const peek = shallowRef<{ w: number; h: number; rank: Map<number, number> } | null>(null)
watchEffect(async () => {
  const f = props.files
  peek.value = null
  try {
    const text = (await readSidecar(f.evidence!.bytes).catch(() => null)) ?? (f.sidecar ? new TextDecoder().decode(f.sidecar.bytes) : null)
    if (text === null || props.files !== f) return
    const sc = JSON.parse(text)
    const w = Number(sc.manifest?.w), h = Number(sc.manifest?.h)
    const rank = new Map<number, number>()
    ;(sc.visible ?? []).forEach((p: [number, string], r: number) => rank.set(p[0], r))
    peek.value = w > 0 && h > 0 ? { w, h, rank } : null
  } catch {
    peek.value = null
  }
})

const current = computed(() => props.checks.findIndex((c) => c.state === 'running'))
const doneCount = computed(() => props.checks.filter((c) => !['pending', 'running'].includes(c.state)).length)
const v3 = computed(() => props.checks.find((c) => c.id === 'V3')!)
const headline = computed(() => {
  const c = props.checks[current.value]
  if (!c) return 'Starting the verifier…'
  const what: Record<string, string> = { V1: 'Checking the signature', V2: "Looking up the authority's ledger record", V3: 'Rehashing the visible tiles', V4: "Looking up this copy's ledger record", V5: 'Checking the redaction rules', V6: 'Rebuilding the published version' }
  return what[c.id]!
})
const segFill = (k: number) => {
  const c = props.checks[k]!
  if (c.state === 'running') {
    const f = c.id === 'V3' && props.leaves ? Math.round((props.leaves[0] / Math.max(1, props.leaves[1])) * 100) : 40
    return `linear-gradient(90deg, var(--signal) ${f}%, var(--line) ${f}%)`
  }
  return c.state === 'pending' ? 'var(--line)' : 'var(--ink)'
}
function tileState(i: number): 'done' | 'current' | 'waiting' {
  if (v3.value.state !== 'running' && v3.value.state !== 'pending') return 'done'
  if (v3.value.state === 'pending') return 'waiting'
  const r = peek.value?.rank.get(i)
  if (r === undefined) return 'done' // hidden: leaf hash comes from the sidecar
  const d = props.leaves?.[0] ?? 0
  return r < d ? 'done' : r === d ? 'current' : 'waiting'
}
const elapsed = ref(0)
let timer: ReturnType<typeof setInterval> | undefined
onMounted(() => {
  const t0 = performance.now()
  timer = setInterval(() => (elapsed.value = (performance.now() - t0) / 1000), 100)
})
onBeforeUnmount(() => clearInterval(timer))
</script>

<template>
  <main class="page">
    <div class="files">
      <span v-for="f in [files.evidence, files.sidecar, files.rendition].filter(Boolean)" :key="f!.name" class="mono fchip">{{ f!.name }}</span>
      <div class="spacer" />
      <button type="button" class="btn-quiet btn btn-sm" @click="$emit('cancel')">Cancel</button>
    </div>

    <div class="run card">
      <div class="run-word">
        <VIcon name="spin" :size="30" :stroke="1.8" style="color: var(--signal)" />
        <span class="display word">Verifying</span>
      </div>
      <div class="run-body">
        <div class="run-line"><span class="run-title">{{ headline }}</span><span class="faint">{{ doneCount }} of 6 done, {{ elapsed.toFixed(1) }} s</span></div>
        <div class="segs" role="progressbar" :aria-valuenow="doneCount" aria-valuemin="0" aria-valuemax="6" aria-label="Checks completed">
          <div v-for="k in 6" :key="k" class="seg-bar" :style="{ background: segFill(k - 1) }" />
        </div>
      </div>
    </div>

    <div class="cols">
      <div class="img-col">
        <ImageFrame v-if="peek" :bytes="files.evidence!.bytes" :width="peek.w" :height="peek.h" alt="Evidence image being verified">
          <TileMask :width="peek.w" :height="peek.h" mode="progress" :done="tileState" />
        </ImageFrame>
        <div class="legend">
          <span><i class="sw sw-done" />Rehashed</span>
          <span><i class="sw sw-wait" />Not yet</span>
        </div>
      </div>
      <div class="side">
        <ChecksSection title="Checks"><CheckList :checks="checks" :leaves="leaves" compact /></ChecksSection>
      </div>
    </div>
  </main>
</template>

<style scoped>
.page { width: 100%; max-width: 1280px; margin: 0 auto; padding: 28px clamp(16px, 4vw, 40px) 48px; display: flex; flex-direction: column; gap: 24px; }
.files { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.fchip { font-size: 12.5px; padding: 6px 10px; border-radius: var(--r-sm); background: var(--surface); border: 1px solid var(--line); }
.spacer { flex: 1; }
.run { display: flex; align-items: stretch; overflow: hidden; flex-wrap: wrap; }
.run-word { background: var(--run-bg); color: var(--ink-2); padding: 22px 28px; display: flex; align-items: center; gap: 14px; }
.word { font-size: clamp(22px, 2.6vw, 32px); }
.run-body { padding: 18px 24px; display: flex; flex-direction: column; justify-content: center; gap: 10px; flex: 1 1 320px; }
.run-line { display: flex; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.run-title { font-size: 16px; font-weight: 600; }
.run-line .mono { font-size: 13px; }
.segs { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 4px; }
.seg-bar { height: 6px; border-radius: 3px; transition: background 0.2s; }
.cols { display: flex; flex-wrap: wrap; gap: 24px; align-items: flex-start; }
.img-col { flex: 999 1 560px; min-width: 0; display: flex; flex-direction: column; gap: 12px; }
.legend { display: flex; gap: 18px; flex-wrap: wrap; font-size: 13px; color: var(--ink-2); align-items: center; }
.legend span { display: inline-flex; align-items: center; gap: 8px; }
.legend .mono { font-size: 12.5px; }
.sw { width: 14px; height: 14px; display: inline-block; }
.sw-done { border: 1px solid var(--ink); }
.sw-wait { background: rgba(245, 244, 238, 0.82); border: 1px solid var(--line); }
.side { flex: 1 1 340px; min-width: 0; display: flex; flex-direction: column; gap: 16px; }
.log { padding: 16px 18px; display: flex; flex-direction: column; gap: 6px; font-size: 12px; line-height: 1.55; }
.log-label { font-family: var(--font-text); color: var(--insp-soft); margin-bottom: 4px; }
</style>
