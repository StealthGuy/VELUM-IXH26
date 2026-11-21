<script setup lang="ts">
import type { Check, Verdict } from '~/lib/velum'

const props = defineProps<{ verdict: Verdict; checks: Check[]; authority: string | null; ms: number; error?: string | null }>()
defineEmits<{ retry: [] }>()

const failed = computed(() => props.checks.filter((c) => c.state === 'fail'))
const unknown = computed(() => props.checks.filter((c) => c.state === 'unknown'))
const passed = computed(() => props.checks.filter((c) => c.state === 'pass'))
const applicable = computed(() => props.checks.filter((c) => c.state !== 'skipped'))

const sentence = computed(() => {
  const who = props.authority ?? 'an authority that is not on the trust list'
  if (props.verdict === 'verified') return `Signed by ${who}. Every redaction since then is recorded on the XRP Ledger.`
  if (props.verdict === 'rejected') {
    const ids = failed.value.map((c) => c.id)
    if (ids.includes('V1')) return props.authority ? `The signature doesn't match ${who}.` : "The signer isn't on the trust list, or the signature is invalid."
    if (ids.includes('V3')) return `Some pixels were changed after ${who} signed the image.`
    if (ids.includes('V2') || ids.includes('V4')) return "The ledger records don't match these files."
    if (ids.includes('V5')) return "The redaction history doesn't follow the rules."
    return "The published version wasn't made from this evidence."
  }
  if (props.error) return props.error
  return "The XRP Ledger couldn't be reached, so the image couldn't be fully checked. That doesn't mean it's fake."
})
const look = computed(() => ({
  verified: { bg: 'var(--ok-bg)', fg: 'var(--ok-fg)', mark: '#9CF0BF', icon: 'check' as const, word: 'Verified' },
  rejected: { bg: 'var(--bad-bg)', fg: 'var(--bad-fg)', mark: '#FF8A63', icon: 'cross' as const, word: 'Rejected' },
  unknown: { bg: 'var(--warn-bg)', fg: 'var(--warn-fg)', mark: 'var(--lemon)', icon: 'warn' as const, word: 'Could not verify' },
}[props.verdict]))
const summary = computed(() => {
  if (props.verdict === 'verified') return `Checked in ${(props.ms / 1000).toFixed(1)} s`
  if (props.verdict === 'rejected') return `${failed.value.length} of ${applicable.value.length} checks failed`
  return unknown.value.length ? `${unknown.value.map((c) => c.id).join(' and ')} not checked` : ''
})
function chipStyle(c: Check) {
  if (c.state === 'fail') return { background: 'var(--bad-bg)', color: 'var(--bad-fg)', boxShadow: 'inset 0 0 0 1.5px var(--bad-mark)', fontWeight: 700 }
  if (c.state === 'unknown') return { background: 'var(--warn-bg)', color: 'var(--warn-fg)' }
  if (props.verdict === 'verified' && c.state === 'pass') return { background: 'var(--ok-bg)', color: 'var(--ok-fg)' }
  return { background: 'var(--paper-2)', color: 'var(--ink-2)' }
}
const mark = (c: Check) => ({ pass: '✓', fail: '✗', unknown: '?', skipped: '–', pending: '·', running: '…' })[c.state]
const showChecks = ref(false)
</script>

<template>
  <section aria-label="Result" class="banner" :class="{ stamp: verdict !== 'unknown' }">
    <div class="verdict" :style="{ background: look.bg, color: look.fg }">
      <div class="badge"><VIcon :name="look.icon" :size="28" :style="{ color: look.mark }" /></div>
      <h1 class="display word" :class="{ long: verdict === 'unknown' }">{{ look.word }}</h1>
    </div>
    <div class="body">
      <span class="sentence">{{ sentence }}</span>
      <div class="chips">
        <span v-for="c in (showChecks ? checks : [])" :key="c.id" class="vchip" :style="chipStyle(c)" :title="c.title">{{ c.id }} {{ mark(c) }}</span>
        <button v-if="summary" type="button" class="sum" :aria-expanded="showChecks" @click="showChecks = !showChecks">{{ summary }}<VIcon name="chevron" :size="14" :class="{ up: showChecks }" /></button>
      </div>
    </div>
    <div class="actions">
      <button v-if="verdict === 'unknown'" type="button" class="btn btn-md" @click="$emit('retry')">Retry</button>
      <slot name="actions" />
    </div>
  </section>
</template>

<style scoped>
.banner { display: flex; flex-wrap: wrap; align-items: stretch; background: var(--surface); border: 1.5px solid var(--ink); border-radius: 14px; overflow: hidden; }
.banner.stamp { box-shadow: 0 5px 0 var(--ink); }
.verdict { padding: 26px 32px; display: flex; align-items: center; gap: 16px; border-right: 1.5px solid var(--ink); }
.badge { width: 52px; height: 52px; border-radius: 10px; background: var(--ink); display: flex; align-items: center; justify-content: center; flex: none; }
.word { margin: 0; font-size: clamp(30px, 4vw, 52px); line-height: 1; }
.word.long { font-size: clamp(24px, 2.8vw, 34px); max-width: 9ch; line-height: 1.02; }
.body { padding: 20px 28px; display: flex; flex-direction: column; justify-content: center; gap: 12px; flex: 1 1 300px; min-width: 0; }
.sentence { font-size: 18px; font-weight: 600; text-wrap: pretty; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.vchip { font-size: 12px; font-weight: 600; padding: 4px 8px; border-radius: var(--r-sm); }
.sum { font-size: 13px; color: var(--ink-2); border: 0; background: none; padding: 2px 4px; display: inline-flex; align-items: center; gap: 4px; cursor: pointer; border-radius: 4px; }
.sum:hover { color: var(--ink); background: var(--paper); }
.sum svg { transition: transform 0.15s; }
.sum svg.up { transform: rotate(180deg); }
.actions { padding: 16px 24px; display: flex; flex-direction: column; justify-content: center; align-items: stretch; gap: 10px; border-left: 1px solid var(--paper-2); }
.actions:empty { display: none; }
</style>
