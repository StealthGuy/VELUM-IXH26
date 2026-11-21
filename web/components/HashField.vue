<script setup lang="ts">
const props = defineProps<{ label: string; value: string; href?: string | null }>()
const copied = ref(false)
async function copy() {
  await copyText(props.value)
  copied.value = true
  setTimeout(() => (copied.value = false), 1200)
}
</script>

<template>
  <div class="hf">
    <span class="label">{{ label }}</span>
    <div class="box">
      <span class="mono val" :title="value">{{ hashGroups(value) }}</span>
      <a v-if="href" :href="href" target="_blank" rel="noopener" class="icon-btn link" aria-label="Open in XRPL Explorer"><VIcon name="external" /></a>
      <button type="button" class="icon-btn" :aria-label="`Copy ${label}`" @click="copy"><VIcon :name="copied ? 'check' : 'copy'" /></button>
    </div>
  </div>
</template>

<style scoped>
.hf { display: flex; flex-direction: column; gap: 6px; }
.box { display: flex; align-items: center; gap: 4px; background: var(--paper); border-radius: var(--r-sm); padding: 4px 4px 4px 12px; }
.val { flex: 1; font-size: 13px; letter-spacing: 0.02em; }
.link { color: var(--signal); }
</style>
