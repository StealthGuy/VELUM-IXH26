<script setup lang="ts">
/** A card whose V1–V6 content opens and closes from its header. Closed by default. */
const props = withDefaults(defineProps<{ title?: string; open?: boolean }>(), { title: 'Checks', open: false })
const isOpen = ref(props.open)
const id = useId()
</script>

<template>
  <section class="card cs">
    <button type="button" class="cs-head" :aria-expanded="isOpen" :aria-controls="id" @click="isOpen = !isOpen">
      <h2>{{ title }}</h2>
      <VIcon name="chevron" :size="18" class="chev" :class="{ open: isOpen }" />
    </button>
    <div v-show="isOpen" :id="id" class="cs-body"><slot /></div>
  </section>
</template>

<style scoped>
.cs { overflow: hidden; }
.cs-head { width: 100%; min-height: 52px; padding: 0 16px 0 20px; display: flex; justify-content: space-between; align-items: center; gap: 12px; border: 0; background: transparent; color: var(--ink); cursor: pointer; text-align: left; }
.cs-head:hover { background: var(--paper); }
.cs-head h2 { margin: 0; font-size: 16px; font-weight: 600; }
.chev { color: var(--ink-2); transition: transform 0.15s; flex: none; }
.chev.open { transform: rotate(180deg); }
.cs-body { border-top: 1px solid var(--paper-2); }
.cs-body :deep(.list) { border: 0; border-radius: 0; }
</style>
