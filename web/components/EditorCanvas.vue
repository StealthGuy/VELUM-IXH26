<script setup lang="ts">
/**
 * Tile grid editor (frontend-spec.md 5, steps 2-3). One SVG overlay at the image's tile scale:
 * click or drag to hide tiles, drag to crop in whole tiles. Ancestor tiles are locked.
 * Keyboard: arrows move the cursor, Space/Enter toggles the tile.
 */
import type { Crop } from '~/lib/velum'

const props = defineProps<{
  bytes: Uint8Array
  width: number
  height: number
  tool: 'hide' | 'crop'
  hiddenLevel: number[] // level that hid each tile in the parent chain, -1 = visible
  pending: Set<number>
  crop: Crop | null
  outside: Set<number>
  newLevel: number
}>()
const emit = defineEmits<{ paint: [tiles: number[], add: boolean]; strokeStart: []; crop: [crop: Crop | null] }>()

const T = 64
const cols = computed(() => Math.ceil(props.width / T))
const rows = computed(() => Math.ceil(props.height / T))
const n = computed(() => cols.value * rows.value)
const svg = ref<SVGSVGElement | null>(null)
const hover = ref<number | null>(null)
const cursor = ref(0)
const focused = ref(false)
let painting: { add: boolean } | null = null
let cropStart: number | null = null
const newColor = computed(() => levelColor(props.newLevel))

const rect = (i: number) => {
  const x = (i % cols.value) * T
  const y = Math.floor(i / cols.value) * T
  return { x, y, w: Math.min(T, props.width - x), h: Math.min(T, props.height - y) }
}
const locked = (i: number) => (props.hiddenLevel[i] ?? -1) >= 0
const editable = (i: number) => !locked(i) && !props.outside.has(i)

function tileAt(e: PointerEvent): number | null {
  const el = svg.value
  if (!el) return null
  const b = el.getBoundingClientRect()
  const x = ((e.clientX - b.left) / b.width) * props.width
  const y = ((e.clientY - b.top) / b.height) * props.height
  if (x < 0 || y < 0 || x >= props.width || y >= props.height) return null
  return Math.floor(y / T) * cols.value + Math.floor(x / T)
}

function cropFrom(a: number, b: number): Crop {
  const ca = a % cols.value, ra = Math.floor(a / cols.value)
  const cb = b % cols.value, rb = Math.floor(b / cols.value)
  return [Math.min(ca, cb), Math.min(ra, rb), Math.abs(ca - cb) + 1, Math.abs(ra - rb) + 1]
}

function down(e: PointerEvent) {
  const t = tileAt(e)
  if (t === null) return
  ;(e.target as Element).setPointerCapture?.(e.pointerId)
  cursor.value = t
  if (props.tool === 'crop') {
    cropStart = t
    emit('strokeStart')
    emit('crop', cropFrom(t, t))
    return
  }
  if (!editable(t)) return
  painting = { add: !props.pending.has(t) }
  emit('strokeStart')
  emit('paint', [t], painting.add)
}
function move(e: PointerEvent) {
  const t = tileAt(e)
  hover.value = t
  if (t === null) return
  if (cropStart !== null) emit('crop', cropFrom(cropStart, t))
  else if (painting && editable(t) && props.pending.has(t) !== painting.add) emit('paint', [t], painting.add)
}
function up() {
  painting = null
  cropStart = null
}

function key(e: KeyboardEvent) {
  const c = cursor.value % cols.value, r = Math.floor(cursor.value / cols.value)
  const go = (nc: number, nr: number) => {
    cursor.value = Math.max(0, Math.min(rows.value - 1, nr)) * cols.value + Math.max(0, Math.min(cols.value - 1, nc))
    e.preventDefault()
  }
  if (e.key === 'ArrowLeft') go(c - 1, r)
  else if (e.key === 'ArrowRight') go(c + 1, r)
  else if (e.key === 'ArrowUp') go(c, r - 1)
  else if (e.key === 'ArrowDown') go(c, r + 1)
  else if ((e.key === ' ' || e.key === 'Enter') && props.tool === 'hide' && editable(cursor.value)) {
    e.preventDefault()
    emit('strokeStart')
    emit('paint', [cursor.value], !props.pending.has(cursor.value))
  }
}

const gridPath = computed(() => {
  const l: string[] = []
  for (let c = 1; c < cols.value; c++) l.push(`M${c * T} 0V${props.height}`)
  for (let r = 1; r < rows.value; r++) l.push(`M0 ${r * T}H${props.width}`)
  return l.join('')
})
const cropBox = computed(() => {
  if (!props.crop) return null
  const [c0, r0, cs, rs] = props.crop
  const x = c0 * T, y = r0 * T
  const w = Math.min(cs * T, props.width - x), h = Math.min(rs * T, props.height - y)
  return { x, y, w, h, label: `${w} × ${h} px` }
})
const tiles = computed(() => {
  const out: { i: number; kind: 'locked' | 'outside' | 'pending'; r: ReturnType<typeof rect>; k: number }[] = []
  for (let i = 0; i < n.value; i++) {
    if (locked(i)) out.push({ i, kind: 'locked', r: rect(i), k: props.hiddenLevel[i]! })
    else if (props.outside.has(i)) out.push({ i, kind: 'outside', r: rect(i), k: 0 })
    else if (props.pending.has(i)) out.push({ i, kind: 'pending', r: rect(i), k: props.newLevel })
  }
  return out
})
const hoverText = computed(() => {
  const t = hover.value ?? (focused.value ? cursor.value : null)
  if (t === null) return ''
  const state = locked(t) ? 'already hidden in this copy, can\'t be uncovered' : props.outside.has(t) ? 'outside the crop' : props.pending.has(t) ? 'will be blacked out' : 'visible'
  return `Tile ${tileXY(t, cols.value)}: ${state}`
})
const url = ref<string | null>(null)
watch(() => props.bytes, (b, _, clean) => {
  const u = URL.createObjectURL(new Blob([b as BlobPart], { type: 'image/png' }))
  url.value = u
  clean(() => URL.revokeObjectURL(u))
}, { immediate: true })
defineExpose({ hoverText })
</script>

<template>
  <div class="stage" :style="{ aspectRatio: `${width} / ${height}` }">
    <img v-if="url" :src="url" alt="Parent level evidence" draggable="false">
    <svg
      ref="svg" :viewBox="`0 0 ${width} ${height}`" preserveAspectRatio="none" class="ov" :class="tool"
      tabindex="0" role="application" :aria-label="`Tile grid, ${cols} by ${rows}. Arrow keys move, Space toggles a tile.`"
      @pointerdown="down" @pointermove="move" @pointerup="up" @pointercancel="up" @pointerleave="hover = null"
      @keydown="key" @focus="focused = true" @blur="focused = false"
    >
      <defs>
        <pattern id="ed-pend" width="16" height="16" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="16" height="16" fill="rgba(18,19,46,0.35)" /><rect width="7" height="16" :fill="newColor.stroke" fill-opacity="0.75" />
        </pattern>
      </defs>
      <path :d="gridPath" stroke="rgba(255,255,255,0.28)" stroke-width="1" vector-effect="non-scaling-stroke" fill="none" />
      <template v-for="t in tiles" :key="t.i">
        <rect v-if="t.kind === 'locked'" :x="t.r.x + 2.5" :y="t.r.y + 2.5" :width="t.r.w - 5" :height="t.r.h - 5" fill="none" :stroke="levelColor(t.k).stroke" stroke-width="5" />
        <rect v-else-if="t.kind === 'outside'" :x="t.r.x" :y="t.r.y" :width="t.r.w" :height="t.r.h" fill="rgba(18,19,46,0.7)" />
        <rect v-else :x="t.r.x + 2.5" :y="t.r.y + 2.5" :width="t.r.w - 5" :height="t.r.h - 5" fill="url(#ed-pend)" :stroke="newColor.stroke" stroke-width="5" />
      </template>
      <rect v-if="hover !== null && tool === 'hide' && editable(hover)" :x="rect(hover).x" :y="rect(hover).y" :width="rect(hover).w" :height="rect(hover).h" fill="rgba(255,255,255,0.12)" stroke="#fff" stroke-width="2" vector-effect="non-scaling-stroke" />
      <rect v-if="focused" :x="rect(cursor).x" :y="rect(cursor).y" :width="rect(cursor).w" :height="rect(cursor).h" fill="none" stroke="#2F3FE0" stroke-width="3" vector-effect="non-scaling-stroke" />
      <g v-if="cropBox" pointer-events="none">
        <rect :x="cropBox.x" :y="cropBox.y" :width="cropBox.w" :height="cropBox.h" fill="none" stroke="#fff" stroke-width="2.5" vector-effect="non-scaling-stroke" />
        <rect v-for="(p, k) in [[cropBox.x, cropBox.y], [cropBox.x + cropBox.w, cropBox.y], [cropBox.x, cropBox.y + cropBox.h], [cropBox.x + cropBox.w, cropBox.y + cropBox.h]]" :key="k" :x="p[0]! - 7" :y="p[1]! - 7" width="14" height="14" fill="#fff" stroke="#12132E" stroke-width="2" />
      </g>
    </svg>
    <span v-if="cropBox" class="mono crop-label" :style="{ left: `${(cropBox.x / width) * 100}%`, top: `${(cropBox.y / height) * 100}%` }">{{ cropBox.label }}</span>
  </div>
</template>

<style scoped>
.stage { position: relative; width: 100%; box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.15); user-select: none; touch-action: none; }
img { position: absolute; inset: 0; width: 100%; height: 100%; display: block; }
.ov { position: absolute; inset: 0; width: 100%; height: 100%; display: block; cursor: pointer; outline: none; }
.ov.crop { cursor: crosshair; }
.ov:focus-visible { outline: 2px solid var(--signal); outline-offset: 3px; }
.crop-label { position: absolute; transform: translateY(calc(-100% - 6px)); font-size: 11.5px; background: #fff; color: var(--ink); padding: 3px 6px; white-space: nowrap; pointer-events: none; }
</style>
