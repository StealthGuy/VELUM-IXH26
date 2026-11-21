<script setup lang="ts">
const props = withDefaults(defineProps<{ level: number; suffix?: string; size?: 'sm' | 'md' }>(), { suffix: '', size: 'md' })
const c = computed(() => levelColor(props.level))
</script>

<template>
  <span class="display lc" :class="size" :style="{ background: c.fill, color: c.text, boxShadow: level > 0 ? `inset 0 0 0 1.5px ${c.stroke}` : 'none' }">L{{ level }}<template v-if="suffix"> · {{ suffix }}</template></span>
</template>

<style scoped>
.lc { font-size: 12px; padding: 5px 8px; border-radius: var(--r-sm); white-space: nowrap; display: inline-block; line-height: 1.2; }
.lc.sm { font-size: 10.5px; padding: 3px 6px; border-radius: 3px; }
</style>
