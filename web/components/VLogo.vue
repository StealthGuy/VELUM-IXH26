<script setup lang="ts">
withDefaults(defineProps<{ size?: number; stroke?: string }>(), { size: 24, stroke: '#12132E' })
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 22 22" aria-hidden="true">
    <rect x="1" y="1" width="5.5" height="5.5" fill="none" :stroke="stroke" stroke-width="1.2" />
    <rect x="8.25" y="1" width="5.5" height="5.5" :fill="stroke" />
    <rect x="15.5" y="1" width="5.5" height="5.5" fill="none" :stroke="stroke" stroke-width="1.2" />
    <rect x="1" y="8.25" width="5.5" height="5.5" fill="none" :stroke="stroke" stroke-width="1.2" />
    <rect x="8.25" y="8.25" width="5.5" height="5.5" fill="none" :stroke="stroke" stroke-width="1.2" />
    <rect x="15.5" y="8.25" width="5.5" height="5.5" :fill="stroke" />
    <rect x="1" y="15.5" width="5.5" height="5.5" fill="#9CF0BF" :stroke="stroke" stroke-width="1.2" />
    <rect x="8.25" y="15.5" width="5.5" height="5.5" fill="none" :stroke="stroke" stroke-width="1.2" />
    <rect x="15.5" y="15.5" width="5.5" height="5.5" fill="none" :stroke="stroke" stroke-width="1.2" />
  </svg>
</template>
