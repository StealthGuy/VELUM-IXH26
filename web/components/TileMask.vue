<script setup lang="ts">
/**
 * SVG overlay drawn at the image's real tile scale (64 px). Modes:
 *  - mask:     hidden tiles outlined in the colour of the level that hid them, crop hatched
 *  - thumb:    same, as a small standalone picture of one level's mask
 *  - progress: leaves recomputed vs waiting (verifying screen)
 *  - reject:   tiles that fail V3 highlighted
 */
const props = withDefaults(defineProps<{
  width: number
  height: number
  mode: 'mask' | 'thumb' | 'progress' | 'reject'
  hiddenLevel?: number[]
  uptoLevel?: number
  cropOutside?: number[]
  badTiles?: number[]
  done?: (i: number) => 'done' | 'current' | 'waiting'
  grid?: boolean
  label?: string
}>(), { hiddenLevel: () => [], uptoLevel: Infinity, cropOutside: () => [], badTiles: () => [], done: undefined, grid: false, label: '' })

const T = 64
const uid = useId()
const cols = computed(() => Math.ceil(props.width / T))
const rows = computed(() => Math.ceil(props.height / T))
const rect = (i: number) => {
  const x = (i % cols.value) * T
  const y = Math.floor(i / cols.value) * T
  return { x, y, w: Math.min(T, props.width - x), h: Math.min(T, props.height - y) }
}
const cropSet = computed(() => new Set(props.cropOutside))
const hiddenTiles = computed(() => {
  const out: { i: number; k: number; r: ReturnType<typeof rect>; crop: boolean; later: boolean }[] = []
  props.hiddenLevel.forEach((k, i) => {
    if (k < 0) return
    if (k > props.uptoLevel) {
      if (props.mode === 'thumb') out.push({ i, k, r: rect(i), crop: false, later: true })
      return
    }
    out.push({ i, k, r: rect(i), crop: cropSet.value.has(i) && (props.mode === 'thumb' ? k === props.uptoLevel : true), later: false })
  })
  return out
})
const levelsUsed = computed(() => [...new Set(hiddenTiles.value.filter((t) => t.crop && !t.later).map((t) => t.k))])
const gridLines = computed(() => {
  const l: string[] = []
  for (let c = 1; c < cols.value; c++) l.push(`M${c * T} 0V${props.height}`)
  for (let r = 1; r < rows.value; r++) l.push(`M0 ${r * T}H${props.width}`)
  return l.join('')
})
const sw = computed(() => (props.mode === 'thumb' ? 10 : 5))
</script>

<template>
  <svg :viewBox="`0 0 ${width} ${height}`" preserveAspectRatio="none" :role="label ? 'img' : undefined" :aria-label="label || undefined" :aria-hidden="label ? undefined : 'true'" class="tm">
    <defs>
      <pattern v-for="k in levelsUsed" :id="`${uid}-crop-${k}`" :key="k" width="18" height="18" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <rect width="18" height="18" fill="#12132E" /><rect width="6" height="18" :fill="levelColor(k).stroke" />
      </pattern>
    </defs>

    <template v-if="mode === 'mask' || mode === 'thumb'">
      <path v-if="grid" :d="gridLines" stroke="rgba(245,244,238,0.28)" stroke-width="1" fill="none" vector-effect="non-scaling-stroke" />
      <template v-for="t in hiddenTiles" :key="t.i">
        <rect v-if="t.later" :x="t.r.x" :y="t.r.y" :width="t.r.w" :height="t.r.h" fill="#D8D6CC" />
        <rect v-else-if="t.crop" :x="t.r.x" :y="t.r.y" :width="t.r.w" :height="t.r.h" :fill="`url(#${uid}-crop-${t.k})`" />
        <rect v-else :x="t.r.x + sw / 2" :y="t.r.y + sw / 2" :width="t.r.w - sw" :height="t.r.h - sw" :fill="mode === 'thumb' ? '#12132E' : 'rgba(0,0,0,0.25)'" :stroke="levelColor(t.k).stroke" :stroke-width="sw" />
      </template>
    </template>

    <template v-else-if="mode === 'progress' && done">
      <template v-for="i in cols * rows" :key="i">
        <rect v-if="done(i - 1) === 'waiting'" :x="rect(i - 1).x" :y="rect(i - 1).y" :width="rect(i - 1).w" :height="rect(i - 1).h" fill="rgba(245,244,238,0.82)" stroke="rgba(18,19,46,0.12)" stroke-width="1" vector-effect="non-scaling-stroke" />
        <rect v-else-if="done(i - 1) === 'current'" :x="rect(i - 1).x + 2" :y="rect(i - 1).y + 2" :width="rect(i - 1).w - 4" :height="rect(i - 1).h - 4" fill="rgba(47,63,224,0.25)" stroke="#2F3FE0" stroke-width="4" />
        <rect v-else :x="rect(i - 1).x" :y="rect(i - 1).y" :width="rect(i - 1).w" :height="rect(i - 1).h" fill="none" stroke="rgba(245,244,238,0.35)" stroke-width="1" vector-effect="non-scaling-stroke" />
      </template>
    </template>

    <template v-else-if="mode === 'reject'">
      <path :d="gridLines" stroke="rgba(245,244,238,0.18)" stroke-width="1" fill="none" vector-effect="non-scaling-stroke" />
      <g v-for="i in badTiles" :key="i">
        <rect :x="rect(i).x - 4" :y="rect(i).y - 4" :width="rect(i).w + 8" :height="rect(i).h + 8" fill="none" stroke="#FFDCCF" stroke-width="6" />
        <rect :x="rect(i).x + 2" :y="rect(i).y + 2" :width="rect(i).w - 4" :height="rect(i).h - 4" fill="rgba(229,72,28,0.25)" stroke="#E5481C" stroke-width="4" />
        <path :d="`M${rect(i).x + 20} ${rect(i).y + 20}l24 24M${rect(i).x + 44} ${rect(i).y + 20}l-24 24`" stroke="#FFDCCF" stroke-width="5" stroke-linecap="round" />
      </g>
    </template>
  </svg>
</template>

<style scoped>
.tm { position: absolute; inset: 0; width: 100%; height: 100%; display: block; }
</style>
