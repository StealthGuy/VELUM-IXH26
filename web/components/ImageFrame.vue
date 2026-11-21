<script setup lang="ts">
/** Chamfered frame showing PNG bytes via an object URL. Display only: pixels are never read back. */
const props = withDefaults(defineProps<{ bytes: Uint8Array | null; width: number; height: number; alt: string; dim?: boolean; plain?: boolean }>(), { dim: false, plain: false })
const url = ref<string | null>(null)
watch(
  () => props.bytes,
  (b, _, onCleanup) => {
    if (!b) {
      url.value = null
      return
    }
    const u = URL.createObjectURL(new Blob([b as BlobPart], { type: 'image/png' }))
    url.value = u
    onCleanup(() => URL.revokeObjectURL(u))
  },
  { immediate: true },
)
</script>

<template>
  <div class="frame" :class="{ chamfer: !plain }" :style="{ aspectRatio: `${width} / ${height}` }">
    <img v-if="url" :src="url" :alt="alt" :class="{ dim }" draggable="false">
    <slot />
  </div>
</template>

<style scoped>
.frame { position: relative; width: 100%; background: var(--ink); overflow: hidden; }
img { position: absolute; inset: 0; width: 100%; height: 100%; display: block; image-rendering: auto; user-select: none; }
img.dim { filter: saturate(0.55) brightness(0.8); }
</style>
