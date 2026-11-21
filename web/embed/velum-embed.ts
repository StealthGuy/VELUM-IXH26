/**
 * VELUM embed widget (frontend-spec.md 6). Adds a "VELUM · Verify" badge to every img[data-velum]
 * (or with data-velum-evidence / data-velum-sidecar), inside a Shadow DOM. The sidecar normally
 * travels inside the evidence PNG; data-velum-sidecar is only for a PNG without one. Loads nothing heavy until a click.
 * The popover is a convenience; "Full report" opens the Viewer on its own origin, which is the
 * authoritative result. Reads only URLs from the page, never names or pins.
 */
import type { EmbedResult } from './verify-entry'

const SCRIPT = document.currentScript as HTMLScriptElement | null
const BASE = new URL('.', SCRIPT?.src ?? location.href)
const VIEWER = new URL('/', BASE).href

const CSS = `
:host{all:initial}
*{box-sizing:border-box}
.b{position:absolute;left:12px;bottom:12px;height:36px;padding:0 12px 0 8px;border-radius:6px;border:1.5px solid #12132E;background:#F5F4EE;color:#12132E;display:inline-flex;align-items:center;gap:8px;font:600 13px 'Instrument Sans','Helvetica Neue',Arial,sans-serif;cursor:pointer;z-index:2}
.b:focus-visible{outline:2px solid #2F3FE0;outline-offset:2px}
.b.ok{background:#C9F7DA;color:#0B5E33;font-weight:700}.b.bad{background:#FFDCCF;color:#A52714;font-weight:700}.b.unk{background:#FFF3A6;color:#6B5300;font-weight:700}
.w{font:800 11px 'Archivo','Arial Black',sans-serif;font-stretch:125%;letter-spacing:.04em}
.sep{width:1px;height:14px;background:#B9B7AE}
.sp{animation:s .9s linear infinite}@keyframes s{to{transform:rotate(360deg)}}
.p{position:absolute;left:12px;bottom:58px;width:340px;max-width:calc(100% - 24px);background:#F5F4EE;color:#12132E;border:1.5px solid #12132E;border-radius:12px;box-shadow:0 18px 40px -18px rgba(18,19,46,.55);overflow:hidden;font:14px 'Instrument Sans','Helvetica Neue',Arial,sans-serif;z-index:3}
.ph{padding:14px 16px;display:flex;align-items:center;justify-content:space-between;border-bottom:1.5px solid #12132E}
.pt{display:inline-flex;align-items:center;gap:10px;font:800 18px 'Archivo','Arial Black',sans-serif;font-stretch:125%;text-transform:uppercase}
.ic{width:28px;height:28px;border-radius:6px;background:#12132E;display:inline-flex;align-items:center;justify-content:center}
.x{width:36px;height:36px;border:0;background:transparent;color:inherit;border-radius:6px;cursor:pointer;display:inline-flex;align-items:center;justify-content:center}
dl{margin:0;padding:14px 16px;display:grid;grid-template-columns:auto minmax(0,1fr);gap:10px 14px;font-size:13.5px}
dt{color:#3F4160}dd{margin:0;text-align:right;font-weight:600}
.m{font-family:'JetBrains Mono',ui-monospace,Menlo,monospace;font-weight:400;font-size:13px}
.lv{display:flex;gap:4px;justify-content:flex-end}.lv span{font:800 10.5px 'Archivo','Arial Black',sans-serif;font-stretch:125%;padding:3px 6px;border-radius:3px}
.f{padding:0 16px 14px;display:flex;flex-direction:column;gap:10px}
.r{height:44px;border-radius:8px;border:1.5px solid #12132E;background:#12132E;color:#F5F4EE;font-weight:600;font-size:14px;display:flex;align-items:center;justify-content:center;gap:8px;text-decoration:none}
.n{font-size:12px;line-height:1.45;color:#3F4160}
`
const LOGO = '<svg width="18" height="18" viewBox="0 0 22 22" aria-hidden="true">' +
  [[1, 1, 0], [8.25, 1, 1], [15.5, 1, 0], [1, 8.25, 0], [8.25, 8.25, 0], [15.5, 8.25, 1], [1, 15.5, 2], [8.25, 15.5, 0], [15.5, 15.5, 0]]
    .map(([x, y, f]) => `<rect x="${x}" y="${y}" width="5.5" height="5.5" fill="${f === 1 ? '#12132E' : f === 2 ? '#9CF0BF' : 'none'}" stroke="#12132E" stroke-width="1.4"/>`).join('') + '</svg>'
const I = {
  spin: '<svg class="sp" width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="#2F3FE0" stroke-width="2" stroke-linecap="round"><circle cx="8" cy="8" r="5.5" stroke-opacity=".25"/><path d="M13.5 8A5.5 5.5 0 0 0 8 2.5"/></svg>',
  ok: (c: string) => `<svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="${c}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8.5l3.2 3L13 4.5"/></svg>`,
  bad: (c: string) => `<svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="${c}" stroke-width="2.4" stroke-linecap="round"><path d="M4 4l8 8M12 4l-8 8"/></svg>`,
  warn: (c: string) => `<svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="${c}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M8 2.5l6 11H2z"/><path d="M8 7v3"/><path d="M8 12h.01"/></svg>`,
  ext: '<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3h4v4"/><path d="M13 3L7 9"/><path d="M11 9.5V13H3V5h3.5"/></svg>',
  close: '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 4l8 8M12 4l-8 8"/></svg>',
}
const LEVEL = [['#12132E', '#F5F4EE'], ['#D8CCFF', '#12132E'], ['#FFD2B8', '#12132E'], ['#B5EDE6', '#12132E']]
const esc = (s: string) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`)

let verifier: Promise<typeof import('./verify-entry')> | null = null
const load = () => (verifier ??= import(/* @vite-ignore */ new URL('velum-embed-verify.js', BASE).href))

function attach(img: HTMLImageElement) {
  if (img.dataset.velumBound) return
  img.dataset.velumBound = '1'
  const wrap = document.createElement('span')
  wrap.style.cssText = 'position:relative;display:inline-block;line-height:0;max-width:100%'
  img.replaceWith(wrap)
  wrap.appendChild(img)
  const host = document.createElement('span')
  host.style.cssText = 'position:absolute;inset:0;pointer-events:none;line-height:normal'
  wrap.appendChild(host)
  const root = host.attachShadow({ mode: 'closed' })
  root.innerHTML = `<style>${CSS}</style><button class="b" type="button" aria-expanded="false" style="pointer-events:auto">${LOGO}<span class="w">VELUM</span><span class="sep"></span>Check</button>`
  const btn = root.querySelector('button')!
  let pop: HTMLElement | null = null
  let result: EmbedResult | null = null
  const abs = (u: string) => new URL(u, location.href).href
  const urls = { sidecar: img.dataset.velumSidecar ? abs(img.dataset.velumSidecar) : null, evidence: abs(img.dataset.velumEvidence ?? img.src), image: abs(img.currentSrc || img.src) }

  const report = () => {
    const q = new URLSearchParams({ evidence: urls.evidence })
    if (urls.sidecar) q.set('sidecar', urls.sidecar)
    if (urls.image !== urls.evidence) q.set('rendition', urls.image)
    return `${VIEWER}?${q}`
  }
  const closePop = () => {
    pop?.remove()
    pop = null
    btn.setAttribute('aria-expanded', 'false')
  }
  const showPop = (r: EmbedResult) => {
    closePop()
    const look = r.verdict === 'verified' ? ['#C9F7DA', '#0B5E33', I.ok('#9CF0BF'), 'Verified'] : r.verdict === 'rejected' ? ['#FFDCCF', '#A52714', I.bad('#FF8A63'), 'Rejected'] : ['#FFF3A6', '#6B5300', I.warn('#FFF07A'), "Can't verify"]
    const rows = r.verdict === 'unknown'
      ? `<dt>Reason</dt><dd>${r.failed.includes('fetch') ? 'The files could not be downloaded' : 'The XRP Ledger could not be reached'}</dd>`
      : `<dt>Authority</dt><dd>${r.authority ? esc(r.authority) : 'Not on the trust list'}</dd>
         <dt>Signed</dt><dd>${r.signedAt ? new Date(r.signedAt).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }) : '—'}</dd>
         <dt>Blacked out</dt><dd>${r.hiddenPct}</dd>
         <dt>Sidecar</dt><dd>${r.sidecar === 'embedded' ? 'in the PNG' : r.sidecar === 'external' ? 'separate file' : '—'}</dd>
         ${r.failed.length ? `<dt>Failed</dt><dd class="m">${r.failed.join(', ')}</dd>` : ''}`
    pop = document.createElement('div')
    pop.className = 'p'
    pop.setAttribute('role', 'dialog')
    pop.setAttribute('aria-label', 'VELUM verification')
    pop.style.pointerEvents = 'auto'
    pop.innerHTML = `<div class="ph" style="background:${look[0]};color:${look[1]}"><span class="pt"><span class="ic">${look[2]}</span>${look[3]}</span><button class="x" type="button" aria-label="Close">${I.close}</button></div>
      <dl>${rows}</dl>
      <div class="f"><a class="r" href="${esc(report())}" target="_blank" rel="noopener">Full report${I.ext}</a><span class="n">The full report opens in the VELUM Viewer. Trust that page over this box.</span></div>`
    pop.querySelector('.x')!.addEventListener('click', closePop)
    root.appendChild(pop)
    btn.setAttribute('aria-expanded', 'true')
  }
  const setBadge = (r: EmbedResult) => {
    btn.className = `b ${r.verdict === 'verified' ? 'ok' : r.verdict === 'rejected' ? 'bad' : 'unk'}`
    btn.innerHTML = r.verdict === 'verified' ? `${I.ok('#0B5E33')}Verified`
      : r.verdict === 'rejected' ? `${I.bad('#A52714')}Rejected` : `${I.warn('#6B5300')}Couldn't check, retry`
  }

  btn.addEventListener('click', async () => {
    if (pop) return closePop()
    if (result && result.verdict !== 'unknown') return showPop(result)
    btn.className = 'b'
    btn.innerHTML = `${I.spin}Verifying…`
    let r: EmbedResult
    try {
      const mod = await load()
      r = await mod.verifyEmbedded(urls)
    } catch {
      r = { verdict: 'unknown', authority: null, signedAt: null, hiddenPct: '', hiddenTiles: 0, sidecar: null, failed: [] }
    }
    result = r
    setBadge(r)
    showPop(r)
  })
}

function scan() {
  document.querySelectorAll<HTMLImageElement>('img[data-velum], img[data-velum-evidence], img[data-velum-sidecar]').forEach(attach)
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', scan)
else scan()
new MutationObserver(scan).observe(document.documentElement, { childList: true, subtree: true })
