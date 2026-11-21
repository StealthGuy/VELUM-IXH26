<script setup lang="ts">
/** Draws an RGB image computed by velum-js. Display only: nothing is ever read back from it. */
import type { Image } from '~/lib/velum'

const props = defineProps<{ image: Image | null; alt: string }>()
const canvas = ref<HTMLCanvasElement | null>(null)

function draw() {
  const c = canvas.value
  const img = props.image
  if (!c || !img) return
  c.width = img.width
  c.height = img.height
  const ctx = c.getContext('2d')
  if (!ctx) return
  const data = ctx.createImageData(img.width, img.height)
  const src = img.rgb
  const dst = data.data
  for (let s = 0, d = 0; s < src.length; s += 3, d += 4) {
    dst[d] = src[s]!
    dst[d + 1] = src[s + 1]!
    dst[d + 2] = src[s + 2]!
    dst[d + 3] = 255
  }
  ctx.putImageData(data, 0, 0)
}
watch(() => props.image, draw)
onMounted(draw)
</script>

<template>
  <canvas ref="canvas" role="img" :aria-label="alt" :style="{ aspectRatio: image ? `${image.width} / ${image.height}` : '16 / 9' }" />
</template>

<style scoped>
canvas { width: 100%; display: block; border-radius: var(--r-sm); background: var(--paper-2); }
</style>
