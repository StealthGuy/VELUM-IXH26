<script setup lang="ts">
/** The design system's 16-unit stroke icons. */
export type IconName = 'check' | 'cross' | 'warn' | 'spin' | 'wait' | 'download' | 'upload' | 'copy' | 'external' | 'lock' | 'arrow' | 'undo' | 'hide' | 'crop' | 'clear' | 'chevron'

const props = withDefaults(defineProps<{ name: IconName; size?: number; stroke?: number }>(), { size: 16, stroke: undefined })
const widths: Partial<Record<IconName, number>> = { chevron: 2, check: 2.4, cross: 2.4, spin: 2, download: 1.8, arrow: 1.8, external: 1.8 }
const sw = computed(() => props.stroke ?? widths[props.name] ?? 1.6)
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 16 16" fill="none" stroke="currentColor" :stroke-width="sw" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" :class="{ spin: name === 'spin' }">
    <path v-if="name === 'check'" d="M3 8.5l3.2 3L13 4.5" />
    <path v-else-if="name === 'cross'" d="M4 4l8 8M12 4l-8 8" />
    <template v-else-if="name === 'warn'"><path d="M8 2.5l6 11H2z" /><path d="M8 7v3" /><path d="M8 12h.01" /></template>
    <template v-else-if="name === 'spin'"><circle cx="8" cy="8" r="5.5" stroke-opacity="0.25" /><path d="M13.5 8A5.5 5.5 0 0 0 8 2.5" /></template>
    <circle v-else-if="name === 'wait'" cx="8" cy="8" r="5.5" stroke-dasharray="2 2.5" />
    <template v-else-if="name === 'download'"><path d="M8 3v8" /><path d="M4.5 7.5L8 11l3.5-3.5" /><path d="M3 13h10" /></template>
    <template v-else-if="name === 'upload'"><path d="M8 11V3" /><path d="M4.5 6.5L8 3l3.5 3.5" /><path d="M3 13h10" /></template>
    <template v-else-if="name === 'copy'"><rect x="5" y="5" width="8" height="8" rx="1.5" /><path d="M3 10.5V4a1 1 0 0 1 1-1h6.5" /></template>
    <template v-else-if="name === 'external'"><path d="M9 3h4v4" /><path d="M13 3L7 9" /><path d="M11 9.5V13H3V5h3.5" /></template>
    <template v-else-if="name === 'lock'"><rect x="3.5" y="7" width="9" height="6.5" rx="1" /><path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" /></template>
    <template v-else-if="name === 'arrow'"><path d="M3 8h10" /><path d="M9 4l4 4-4 4" /></template>
    <template v-else-if="name === 'undo'"><path d="M5.5 3.5L2.5 6.5l3 3" /><path d="M2.5 6.5h7a4 4 0 0 1 0 8H7" /></template>
    <template v-else-if="name === 'hide'"><rect x="2" y="2" width="5" height="5" fill="currentColor" /><rect x="9" y="2" width="5" height="5" /><rect x="2" y="9" width="5" height="5" /><rect x="9" y="9" width="5" height="5" fill="currentColor" /></template>
    <template v-else-if="name === 'crop'"><path d="M4 1.5V12h10.5" /><path d="M1.5 4H12v10.5" /></template>
    <path v-else-if="name === 'clear'" d="M4 4l8 8M12 4l-8 8" />
    <path v-else-if="name === 'chevron'" d="M4 6l4 4 4-4" />
  </svg>
</template>
