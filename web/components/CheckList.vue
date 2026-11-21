<script setup lang="ts">
import type { Check, CheckState } from '~/lib/velum'

const props = withDefaults(defineProps<{ checks: Check[]; compact?: boolean; showMs?: boolean; leaves?: [number, number] | null }>(), { compact: false, showMs: false, leaves: null })

const look: Record<CheckState, { icon: 'check' | 'cross' | 'spin' | 'wait' | 'warn'; bg: string; fg: string; word: string }> = {
  pass: { icon: 'check', bg: 'var(--ok-bg)', fg: 'var(--ok-fg)', word: 'Passed' },
  fail: { icon: 'cross', bg: 'var(--bad-bg)', fg: 'var(--bad-fg)', word: 'Failed' },
  running: { icon: 'spin', bg: 'var(--run-bg)', fg: 'var(--signal)', word: 'Running' },
  pending: { icon: 'wait', bg: 'var(--paper-2)', fg: 'var(--ink-3)', word: 'Waiting' },
  unknown: { icon: 'warn', bg: 'var(--warn-bg)', fg: 'var(--warn-fg)', word: 'Not checked' },
  skipped: { icon: 'wait', bg: 'var(--paper-2)', fg: 'var(--ink-3)', word: 'Not run' },
}

const waitingText: Record<string, string> = {
  V1: 'Checks the signature on the manifest.',
  V2: 'Looks up the manifest on the XRP Ledger.',
  V3: 'Rehashes every visible tile.',
  V4: 'Looks up each level on the XRP Ledger.',
  V5: 'Compares what each level hid.',
  V6: 'Rebuilds the published version.',
}

function detail(c: Check) {
  if (c.state === 'running' && c.id === 'V3' && props.leaves) return `${props.leaves[0]} of ${props.leaves[1]} visible tiles rehashed`
  if (c.state === 'running') return c.id === 'V2' || c.id === 'V4' ? 'Asking the XRP Ledger…' : 'Working…'
  return c.detail || waitingText[c.id]
}
</script>

<template>
  <ol class="list card">
    <li v-for="c in checks" :key="c.id" class="row" :class="{ compact }">
      <span class="id">{{ c.id }}</span>
      <span class="ic" :style="{ background: c.state === 'pass' && compact ? 'var(--ink)' : look[c.state].bg, color: c.state === 'pass' && compact ? 'var(--paper)' : look[c.state].fg }">
        <VIcon :name="look[c.state].icon" :size="c.state === 'pass' || c.state === 'fail' ? 13 : 15" />
      </span>
      <div class="txt">
        <span class="title">{{ c.title }}</span>
        <span class="detail">{{ detail(c) }}</span>
        <ul v-if="c.reasons.length && c.state !== 'pass'" class="reasons">
          <li v-for="(r, k) in c.reasons" :key="k">{{ sentence(r) }}</li>
        </ul>
      </div>
      <span v-if="showMs && c.ms !== null && c.state !== 'skipped'" class="ms">{{ c.ms < 1000 ? `${c.ms} ms` : `${(c.ms / 1000).toFixed(1)} s` }}</span>
      <span v-else-if="!compact" class="state-tag" :style="{ background: look[c.state].bg, color: look[c.state].fg }">{{ look[c.state].word }}</span>
    </li>
  </ol>
</template>

<style scoped>
.list { list-style: none; margin: 0; padding: 0; overflow: hidden; }
.row { display: grid; grid-template-columns: 40px 26px minmax(0, 1fr) auto; align-items: center; gap: 12px; padding: 12px 20px; border-bottom: 1px solid var(--paper-2); }
.row:last-child { border-bottom: 0; }
.row.compact { grid-template-columns: 34px 26px minmax(0, 1fr); padding: 13px 16px; gap: 10px; }
.id { font-size: 13px; font-weight: 600; color: var(--ink-3); }
.ic { width: 26px; height: 26px; border-radius: 6px; display: inline-flex; align-items: center; justify-content: center; }
.txt { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.title { font-size: 14.5px; font-weight: 600; }
.detail { font-size: 13px; color: var(--ink-2); overflow-wrap: anywhere; }
.reasons { margin: 4px 0 0; padding-left: 16px; font-size: 13px; color: var(--bad-fg); }
.ms { font-size: 12px; color: var(--ink-3); }
</style>
