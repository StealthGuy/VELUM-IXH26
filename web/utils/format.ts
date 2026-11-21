/** Display helpers shared by Viewer and Editor. Raw data from files is always shown in mono. */
import type { Crop, Recipe } from '~/lib/velum'

/** Hashes: groups of 4, elided in the middle ("9f2c 81ab … 03de 77c1"). */
export function hashGroups(hex: string, head = 2, tail = 2): string {
  const g = hex.match(/.{1,4}/g) ?? []
  if (g.length <= head + tail) return g.join(' ')
  return `${g.slice(0, head).join(' ')} … ${g.slice(-tail).join(' ')}`
}

/** Addresses and tx hashes keep 4 + 4. */
export function short(s: string, a = 4, b = 4): string {
  return s.length > a + b + 1 ? `${s.slice(0, a)}…${s.slice(-b)}` : s
}

export function fmtDate(iso: string | null, withTime = true): string {
  if (!iso) return '—'
  const d = new Date(iso)
  const date = d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
  if (!withTime) return date
  const time = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' })
  return `${date}, ${time} UTC`
}

export function fmtShortDate(iso: string | null): string {
  if (!iso) return 'not anchored'
  const d = new Date(iso)
  return `${d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' })}, ${d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' })} UTC`
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

export function pct(part: number, total: number): string {
  return total ? `${((part / total) * 100).toFixed(1)}%` : '0%'
}

export interface LevelColor { stroke: string; fill: string; text: string }

/** L0 ink, then L1 violet, L2 orange, L3 teal, repeating for deeper chains. */
export function levelColor(k: number): LevelColor {
  if (!(k > 0)) return { stroke: '#12132E', fill: '#12132E', text: '#F5F4EE' } // 0, negative or NaN
  const c = [
    { stroke: '#6E4CF5', fill: '#D8CCFF', text: '#12132E' },
    { stroke: '#FF6A2B', fill: '#FFD2B8', text: '#12132E' },
    { stroke: '#0E9C8F', fill: '#B5EDE6', text: '#12132E' },
  ]
  return c[(k - 1) % 3]!
}

export function explorerTx(hash: string, network: string | null | undefined): string | null {
  if (network === 'testnet') return `https://testnet.xrpl.org/transactions/${hash}`
  if (network === 'devnet') return `https://devnet.xrpl.org/transactions/${hash}`
  if (network === 'mainnet') return `https://livenet.xrpl.org/transactions/${hash}`
  return null
}

export function recipeText(crop: Crop | null, recipe: Recipe | null, out?: { width: number; height: number } | null): string {
  const parts: string[] = []
  if (crop) parts.push(`crop ${crop[2]}×${crop[3]} tiles at (${crop[0]}, ${crop[1]})`)
  if (recipe) {
    parts.push(`rotate ${recipe.rotate}°`)
    if (recipe.resize) parts.push(`${recipe.resize[0]}×${recipe.resize[1]}`)
    if (recipe.brightness) parts.push(`bright ${recipe.brightness > 0 ? '+' : ''}${recipe.brightness}`)
    if (recipe.contrast) parts.push(`contrast ${recipe.contrast > 0 ? '+' : ''}${recipe.contrast}`)
  }
  if (!parts.length) return out ? `identity · ${out.width}×${out.height}` : 'identity (no crop, no recipe)'
  return parts.join(' · ')
}

/** The published-version settings as label/value rows. */
export function recipeRows(crop: Crop | null, recipe: Recipe | null): [string, string][] {
  const rows: [string, string][] = []
  rows.push(['Crop', crop ? `${crop[2]} × ${crop[3]} tiles` : 'None'])
  rows.push(['Rotation', recipe?.rotate ? `${recipe.rotate}°` : 'None'])
  rows.push(['Size', recipe?.resize ? `${recipe.resize[0]} × ${recipe.resize[1]} px` : 'Unchanged'])
  const sign = (v: number) => (v > 0 ? `+${v}` : `${v}`)
  rows.push(['Brightness', recipe?.brightness ? sign(recipe.brightness) : 'Unchanged'])
  rows.push(['Contrast', recipe?.contrast ? sign(recipe.contrast) : 'Unchanged'])
  return rows
}

/** Reasons come from the verifier as clauses; show them as sentences. */
export function sentence(s: string): string {
  const t = s.charAt(0).toUpperCase() + s.slice(1)
  return /[.!?]$/.test(t) ? t : `${t}.`
}

export function tileXY(i: number, cols: number): string {
  return `(${i % cols}, ${Math.floor(i / cols)})`
}

export async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    /* clipboard may be blocked; nothing to do */
  }
}

export function downloadBytes(name: string, data: Uint8Array | string, type = 'application/octet-stream') {
  const blob = new Blob([typeof data === 'string' ? data : (data as BlobPart)], { type })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 5000)
}
