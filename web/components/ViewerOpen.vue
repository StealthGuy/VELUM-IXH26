<script setup lang="ts">
import type { LevelFiles, LoadedFile, SampleIndex } from '~/composables/useVelum'

const props = withDefaults(defineProps<{ title?: string; intro?: string; action?: string; error?: string | null }>(), {
  title: 'Verify an image',
  intro: 'Open a VELUM image to see who signed it and what has been blacked out. Its sidecar travels inside the PNG.',
  action: 'Verify image',
  error: null,
})
const emit = defineEmits<{ open: [files: LevelFiles] }>()

type Role = 'evidence' | 'sidecar' | 'rendition'
const files = reactive<Record<Role, LoadedFile | null>>({ evidence: null, sidecar: null, rendition: null })
const problems = reactive<Record<Role, string | null>>({ evidence: null, sidecar: null, rendition: null })
const dragging = ref(false)
const picker = ref<HTMLInputElement | null>(null)
const urls = reactive({ sidecar: '', evidence: '', rendition: '' })
const urlError = ref<string | null>(null)
const busy = ref(false)
const loadingId = ref<string | null>(null)
const samples = ref<SampleIndex | null>(null)

onMounted(async () => {
  try {
    const r = await fetch('/samples/index.json', { cache: 'no-store' })
    if (r.ok) samples.value = await r.json()
  } catch { /* no samples bundled */ }
})

/** Cheap header check so a wrong PNG is flagged on its slot; the verifier re-checks everything. */
function pngProblem(b: Uint8Array): string | null {
  const sig = [137, 80, 78, 71, 13, 10, 26, 10]
  if (b.length < 33 || sig.some((v, i) => b[i] !== v)) return 'Not a PNG file.'
  const depth = b[24], color = b[25], interlace = b[28]
  if (depth !== 8) return `PNG has bit depth ${depth}. VELUM needs 8-bit RGB.`
  if (color !== 2 && color !== 6) return 'PNG is not RGB. VELUM needs 8-bit RGB, no palette or greyscale.'
  if (interlace !== 0) return 'PNG is interlaced. VELUM needs 8-bit RGB, no interlace.'
  return null
}

function roleOf(name: string): Role | null {
  const n = name.toLowerCase()
  if (n.endsWith('.json')) return 'sidecar'
  if (n.endsWith('.public.png')) return 'rendition'
  if (n.endsWith('.png')) return 'evidence'
  return null
}

async function take(list: FileList | File[]) {
  for (const f of Array.from(list)) {
    const role = roleOf(f.name)
    if (!role) continue
    const bytes = new Uint8Array(await f.arrayBuffer())
    files[role] = { name: f.name, bytes }
    problems[role] = role === 'sidecar' ? null : pngProblem(bytes)
  }
}

function onDrop(e: DragEvent) {
  dragging.value = false
  if (e.dataTransfer?.files) take(e.dataTransfer.files)
}

const ready = computed(() => files.evidence && !problems.evidence && !problems.rendition)

function start() {
  if (!ready.value) return
  emit('open', { evidence: files.evidence, sidecar: files.sidecar, rendition: files.rendition, source: 'drop', urls: null, ledger: DEFAULT_LEDGER, network: 'testnet' })
}

async function openUrls() {
  urlError.value = null
  if (!urls.evidence) {
    urlError.value = 'The evidence URL is required.'
    return
  }
  busy.value = true
  try {
    emit('open', await loadFromUrls({ ...urls }))
  } catch (e) {
    urlError.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

async function openSample(id: string) {
  if (!samples.value) return
  busy.value = true
  loadingId.value = id
  try {
    emit('open', await loadSample(samples.value, id))
  } finally {
    busy.value = false
    loadingId.value = null
  }
}

const slots: { role: Role; title: string; hint: string; required: boolean }[] = [
  { role: 'evidence', title: 'Evidence', hint: 'NAME.png', required: true },
  { role: 'sidecar', title: 'Sidecar', hint: 'NAME.velum.json, only if not in the PNG', required: false },
  { role: 'rendition', title: 'Published version', hint: 'NAME.public.png', required: false },
]
const trust = TRUST_LIST.entries
</script>

<template>
  <main class="page">
    <div class="main-col">
      <div class="intro">
        <h1 class="display h1">{{ title }}</h1>
        <p class="lede">{{ intro }}</p>
      </div>

      <div
        class="drop grid-bg" :class="{ over: dragging }"
        @dragover.prevent="dragging = true" @dragleave.prevent="dragging = false" @drop.prevent="onDrop"
      >
        <div class="drop-head">
          <div class="drop-icon"><VIcon name="upload" :size="24" :stroke="1.5" /></div>
          <span class="drop-title">Drop a level here</span>
          <span class="drop-hint">You need the evidence PNG: its sidecar is embedded. Add the .public.png to check the published version, or a .velum.json for a PNG without one.</span>
          <div class="drop-actions">
            <button type="button" class="btn" :class="ready ? '' : 'btn-primary'" @click="picker?.click()">Browse files</button>
            <button v-if="ready" type="button" class="btn btn-primary" @click="start">{{ action }}<VIcon name="arrow" /></button>
          </div>
          <input ref="picker" type="file" multiple accept=".png,.json,image/png,application/json" hidden @change="take(($event.target as HTMLInputElement).files!)">
        </div>
        <div class="slots">
          <div v-for="s in slots" :key="s.role" class="slot" :class="{ filled: files[s.role] && !problems[s.role], bad: problems[s.role], optional: !s.required && !files[s.role] }">
            <template v-if="problems[s.role]">
              <div class="slot-ic bad-ic"><VIcon name="warn" :size="18" /></div>
              <div class="slot-txt"><span class="slot-title">Not accepted</span><span class="slot-err">{{ problems[s.role] }}</span></div>
              <button type="button" class="icon-btn" :aria-label="`Remove ${s.title.toLowerCase()} file`" @click="files[s.role] = null; problems[s.role] = null"><VIcon name="cross" :size="14" /></button>
            </template>
            <template v-else-if="files[s.role]">
              <div class="slot-ic ok-ic"><VIcon name="check" :size="18" /></div>
              <div class="slot-txt"><span class="slot-title">{{ s.title }}</span><span class="slot-sub"><span class="mono">{{ files[s.role]!.name }}</span> <span class="faint">{{ fmtBytes(files[s.role]!.bytes.length) }}</span></span></div>
              <button type="button" class="icon-btn" :aria-label="`Remove ${s.title.toLowerCase()} file`" @click="files[s.role] = null"><VIcon name="cross" :size="14" /></button>
            </template>
            <template v-else>
              <div class="slot-txt">
                <div class="slot-row"><span class="slot-title">{{ s.title }}</span><span class="req" :class="{ opt: !s.required }">{{ s.required ? 'Required' : 'Optional' }}</span></div>
                <span class="mono slot-sub faint">{{ s.hint }}</span>
              </div>
            </template>
          </div>
        </div>
      </div>

      <div v-if="error" class="card note-warn">
        <div class="note-ic"><VIcon name="warn" :size="18" /></div>
        <div><strong>Could not open the files</strong><p>{{ error }}</p></div>
      </div>

      <details class="card urls" open>
        <summary>Or open from URLs</summary>
        <form class="url-grid" @submit.prevent="openUrls">
          <label class="url-f"><span class="label">Sidecar</span><input v-model.trim="urls.sidecar" type="url" class="field" placeholder="optional: https://…/case.velum.json"></label>
          <label class="url-f"><span class="label">Evidence</span><input v-model.trim="urls.evidence" type="url" class="field" placeholder="https://…/street.png"></label>
          <label class="url-f"><span class="label">Published version (optional)</span><input v-model.trim="urls.rendition" type="url" class="field opt-field" placeholder="https://…/street.public.png"></label>
          <button type="submit" class="btn btn-md" :disabled="busy">{{ busy ? 'Fetching…' : 'Open & verify' }}</button>
        </form>
        <div v-if="urlError" class="url-err"><VIcon name="warn" :size="14" />{{ urlError }} Download the files and drop them above instead.</div>
        <p class="url-help">The server hosting the files has to allow cross-origin requests. If it doesn't, download them and drop them above.</p>
      </details>
    </div>

    <aside class="side">
      <div v-if="samples?.samples.length" class="card samples">
        <div class="side-head col"><h2>Try a demo</h2><p class="muted side-sub">{{ samples.network === 'testnet' ? 'Files from a test chain recorded on XRPL Testnet.' : 'Sample files checked against a local test ledger.' }}</p></div>
        <button v-for="s in samples.samples" :key="s.id" type="button" class="sample" :disabled="busy" @click="openSample(s.id)">
          <LevelChip v-if="/^L\d+$/.test(s.level ?? '')" :level="+s.level!.slice(1)" size="sm" />
          <span v-else class="attack">Forged</span>
          <span class="sample-label">{{ s.label }}</span>
          <VIcon :name="loadingId === s.id ? 'spin' : 'arrow'" />
        </button>
      </div>

      <slot name="aside">
        <ChecksSection title="What gets checked">
          <ol class="what">
            <li><span>V1</span><span>The manifest is signed by an authority on the trust list.</span></li>
            <li><span>V2</span><span>The authority recorded that manifest on the XRP Ledger.</span></li>
            <li><span>V3</span><span>The visible pixels are the ones the authority signed.</span></li>
            <li><span>V4</span><span>Each redaction was recorded on the ledger by the account that made it.</span></li>
            <li><span>V5</span><span>Tiles outside the crop are hidden, and the crop and settings can be applied.</span></li>
            <li><span>V6</span><span>The published picture can be rebuilt from the evidence.</span></li>
          </ol>
        </ChecksSection>
      </slot>

      <div class="trust-card">
        <h2 class="tc-title">Trusted authorities</h2>
        <div v-for="e in trust" :key="e.xrpl_address" class="tc-entry">
          <div class="display tc-badge">L0</div>
          <div class="tc-txt"><span class="tc-name">{{ e.name }}</span><span class="tc-addr"><span class="mono">{{ short(e.xrpl_address) }}</span> on {{ e.network === 'testnet' ? 'Testnet' : e.network }}</span></div>
        </div>
        <p class="tc-note">This list is built into the Viewer. Files and links can't add to it.</p>
      </div>
    </aside>
  </main>
</template>

<style scoped>
.page { width: 100%; max-width: 1280px; margin: 0 auto; padding: 48px clamp(16px, 4vw, 40px) 56px; display: flex; flex-wrap: wrap; gap: 40px; align-items: flex-start; }
.main-col { flex: 999 1 560px; min-width: 0; display: flex; flex-direction: column; gap: 28px; }
.intro { display: flex; flex-direction: column; gap: 16px; }
.h1 { margin: 0; font-size: clamp(32px, 4.4vw, 54px); line-height: 1; text-wrap: balance; }
.lede { margin: 0; max-width: 600px; font-size: 17px; line-height: 1.55; color: var(--ink-2); text-wrap: pretty; }

.drop { border: 1.5px dashed var(--ink); border-radius: var(--r-lg); padding: 44px 24px 24px; display: flex; flex-direction: column; align-items: center; gap: 28px; transition: background-color 0.15s; }
.drop.over { background-color: #EEF0FF; border-color: var(--signal); }
.drop-head { display: flex; flex-direction: column; align-items: center; gap: 14px; text-align: center; }
.drop-icon { width: 56px; height: 56px; border-radius: 10px; background: var(--ink); color: var(--paper); display: flex; align-items: center; justify-content: center; }
.drop-title { font-size: 22px; font-weight: 600; }
.drop-hint { font-size: 15px; color: var(--ink-2); max-width: 420px; }
.drop-actions { display: flex; gap: 12px; flex-wrap: wrap; justify-content: center; margin-top: 4px; }
.slots { width: 100%; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(220px, 100%), 1fr)); gap: 12px; }
.slot { background: var(--paper); border-radius: var(--r-md); padding: 14px 16px; display: flex; gap: 12px; align-items: center; border: 1px solid var(--line); min-height: 72px; }
.slot.optional { border-style: dashed; border-color: var(--line-2); }
.slot.filled { background: var(--surface); border: 1.5px solid var(--ink); }
.slot.bad { background: #FFF7F3; border: 1.5px solid var(--bad-mark); }
.slot-ic { width: 40px; height: 40px; border-radius: var(--r-md); display: flex; align-items: center; justify-content: center; flex: none; }
.ok-ic { background: var(--ok-bg); color: var(--ok-fg); }
.bad-ic { background: var(--bad-bg); color: var(--bad-fg); }
.slot-txt { display: flex; flex-direction: column; gap: 3px; flex: 1; min-width: 0; }
.slot-row { display: flex; justify-content: space-between; align-items: center; }
.slot-title { font-size: 14px; font-weight: 600; }
.slot-sub { font-size: 12.5px; color: var(--ink-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.slot-err { font-size: 13px; color: var(--bad-fg); }
.req { font-size: 12.5px; color: var(--ink-2); }
.req.opt { color: var(--ink-3); }

.note-warn { display: flex; gap: 14px; padding: 18px 22px; align-items: flex-start; }
.note-warn p { margin: 4px 0 0; font-size: 14px; color: var(--ink-2); }
.note-ic { width: 40px; height: 40px; flex: none; border-radius: var(--r-md); background: var(--warn-bg); color: var(--warn-fg); display: flex; align-items: center; justify-content: center; }

.urls summary { padding: 16px 20px; font-size: 15px; font-weight: 600; cursor: pointer; }
.url-grid { padding: 0 20px 16px; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(220px, 100%), 1fr)); gap: 14px; align-items: end; }
.url-f { display: flex; flex-direction: column; gap: 6px; }
.opt-field { border-width: 1px; border-color: var(--line-2); }
.url-err { margin: 0 20px 10px; display: flex; gap: 8px; align-items: center; font-size: 13.5px; color: var(--bad-fg); }
.url-help { margin: 0; padding: 0 20px 18px; font-size: 13px; color: var(--ink-2); }

.side { flex: 1 1 320px; min-width: 0; display: flex; flex-direction: column; gap: 20px; }
.side-head { padding: 18px 20px 12px; display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
.side-head h2 { margin: 0; font-size: 16px; font-weight: 600; }
.side-head .mono { font-size: 12px; }
.what { list-style: none; margin: 0; padding: 0; }
.what li { display: grid; grid-template-columns: 40px minmax(0, 1fr); gap: 4px 10px; padding: 12px 20px; border-top: 1px solid var(--paper-2); font-size: 14px; line-height: 1.45; }
.what li > span:first-child { font-size: 13px; font-weight: 600; color: var(--ink-3); }
.what strong { font-weight: 600; }
.samples { overflow: hidden; }
.sample { width: 100%; display: grid; grid-template-columns: 46px minmax(0, 1fr) auto; column-gap: 12px; align-items: center; text-align: left; padding: 12px 20px; border: 0; border-top: 1px solid var(--paper-2); background: transparent; cursor: pointer; color: var(--ink); min-height: 48px; }
.side-head.col { flex-direction: column; align-items: flex-start; gap: 4px; }
.side-sub { margin: 0; font-size: 13.5px; }
.attack { font-size: 11px; font-weight: 700; padding: 3px 6px; border-radius: 3px; background: var(--bad-bg); color: var(--bad-fg); justify-self: start; }
.sample:hover { background: var(--paper); }
.sample:disabled { opacity: 0.6; cursor: wait; }
.sample-label { font-size: 14px; }
.sample > svg { color: var(--signal); }

.trust-card { background: var(--ink); color: var(--insp-text); border-radius: var(--r-lg); padding: 20px; display: flex; flex-direction: column; gap: 12px; }
.tc-title { margin: 0; font-size: 15px; font-weight: 600; color: var(--insp-soft); }
.tc-entry { display: flex; gap: 12px; align-items: center; }
.tc-badge { width: 40px; height: 40px; border-radius: var(--r-md); background: var(--lilac); color: var(--ink); display: flex; align-items: center; justify-content: center; font-size: 12px; flex: none; }
.tc-txt { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.tc-name { font-size: 15px; font-weight: 600; }
.tc-addr { font-size: 12.5px; color: var(--insp-soft); }
.tc-note { margin: 0; font-size: 13px; line-height: 1.5; color: var(--insp-soft); }
</style>
