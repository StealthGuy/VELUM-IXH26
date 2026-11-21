<script setup lang="ts">
const props = defineProps<{ mode: 'verify' | 'redact'; offline?: boolean }>()
const { status, ledger, retry } = useXrplStatus()
const ledgerText = computed(() => (ledger.value ? ledger.value.toLocaleString('en') : ''))
</script>

<template>
  <header class="hdr">
    <NuxtLink to="/" class="brand">
      <VLogo :size="24" />
      <span class="display brand-word">Velum</span>
    </NuxtLink>
    <nav aria-label="Mode" class="seg mode">
      <NuxtLink to="/" :aria-current="mode === 'verify' ? 'page' : undefined">Verify</NuxtLink>
      <NuxtLink to="/edit" :aria-current="mode === 'redact' ? 'page' : undefined">Redact</NuxtLink>
    </nav>
    <slot name="steps" />
    <div class="spacer" />
    <div class="right">
      <slot name="right" />
      <span v-if="offline" class="net">Local test ledger</span>
      <span v-else-if="status === 'online'" class="net" title="Latest ledger closed on XRPL Testnet">
        <span class="net-name">Testnet</span>
        <span class="net-num">{{ ledgerText }}</span>
      </span>
      <span v-else-if="status === 'offline'" class="net net-off">Testnet unreachable <button type="button" class="net-retry" @click="retry">Retry</button></span>
      <span v-else class="net net-wait">Connecting to Testnet…</span>
    </div>
  </header>
</template>

<style scoped>
.hdr { display: flex; flex-wrap: wrap; align-items: center; gap: 12px 24px; padding: 12px clamp(16px, 4vw, 40px); border-bottom: 1px solid var(--line); background: var(--paper); }
.brand { display: flex; align-items: center; gap: 10px; text-decoration: none; color: var(--ink); min-height: 44px; }
.brand-word { font-size: 18px; letter-spacing: 0.02em; }
.mode a { height: 36px; padding: 0 16px; border-radius: 6px; color: var(--ink-2); display: inline-flex; align-items: center; font-size: 14px; font-weight: 600; text-decoration: none; }
.mode a[aria-current='page'] { background: var(--ink); color: var(--paper); }
.spacer { flex: 1 1 0; }
.right { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.net { display: inline-flex; align-items: baseline; gap: 8px; font-size: 13.5px; color: var(--ink-2); }
.net-name { font-weight: 600; color: var(--ink); }
.net-num { font-variant-numeric: tabular-nums; min-width: 9ch; }
.net-off { color: var(--warn-fg); }
.net-wait { color: var(--ink-3); }
.net-retry { border: 0; background: none; padding: 0; color: var(--signal); font-weight: 600; text-decoration: underline; text-underline-offset: 3px; cursor: pointer; }
</style>
