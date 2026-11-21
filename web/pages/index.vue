<script setup lang="ts">
/** A — Viewer: open a level, verify it in a Web Worker, show the result (frontend-spec.md 4). */
import type { LevelFiles } from '~/composables/useVelum'
import { useLevelFiles } from '~/composables/useLevelFiles'

const route = useRoute()
const level = useLevelFiles()
const { state, run, cancel } = useVerifier('viewer')
const openError = ref<string | null>(null)
const screen = computed(() => {
  if (!level.value) return 'open'
  if (state.value.status === 'running') return 'verifying'
  if (state.value.status === 'done' && state.value.report) return 'result'
  return 'open'
})

async function open(files: LevelFiles) {
  openError.value = null
  level.value = files
  await run({ evidence: files.evidence!.bytes, sidecar: files.sidecar?.bytes ?? null, rendition: files.rendition?.bytes ?? null, ledger: files.ledger })
  if (state.value.error) openError.value = `The verifier stopped: ${state.value.error}`
}

function reset() {
  cancel()
  level.value = null
  if (Object.keys(route.query).length) navigateTo('/', { replace: true })
}

function retry() {
  if (level.value) open(level.value)
}

function toEditor() {
  navigateTo('/edit')
}

onMounted(async () => {
  const q = route.query
  if (typeof q.evidence === 'string') {
    try {
      await open(await loadFromUrls({ sidecar: typeof q.sidecar === 'string' ? q.sidecar : '', evidence: q.evidence, rendition: typeof q.rendition === 'string' ? q.rendition : '' }))
    } catch (e) {
      level.value = null
      openError.value = (e as Error).message
    }
  } else if (level.value && state.value.status !== 'done') {
    // came back from the Editor or reloaded mid-run: verify again, never reuse a stale result
    open(level.value)
  }
})
</script>

<template>
  <div class="app">
    <AppHeader mode="verify" />
    <ViewerOpen v-if="screen === 'open'" :error="openError" @open="open" />
    <ViewerVerifying v-else-if="screen === 'verifying'" :files="level!" :checks="state.checks" :leaves="state.leaves" :log="state.log" @cancel="reset" />
    <ViewerResult v-else-if="state.report" :report="state.report" :files="level!" @retry="retry" @edit="toEditor" @reset="reset" />
  </div>
</template>

<style scoped>
.app { min-height: 100vh; display: flex; flex-direction: column; }
</style>
