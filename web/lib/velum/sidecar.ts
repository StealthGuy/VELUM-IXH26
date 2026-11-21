/**
 * Sidecar, manifest and level descriptor types, with the strict parser of VELUM.md section 6.2.
 * Unknown, missing or duplicate keys, wrong lengths, non-integer numbers, or a salt next to a hidden
 * tile make a sidecar invalid. One sidecar describes one copy: its descriptor (`level`) and the
 * transaction that anchored it (`level_tx`); there is no chain of custody (VELUM.md 8.3).
 */
import { isClassicAddress } from './address'
import { parseStrictJson } from './canonical'
import { MAX_SIDE } from './image'
import { MAX_PIXELS } from './png'
import { Grid, TILE } from './tiles'
import { PK_BYTES, SIG_BYTES } from './pq'

export type Rotation = 0 | 90 | 180 | 270

export interface Manifest {
  v: 1
  w: number
  h: number
  tile: 64
  root: string
  authority: string
  pq_alg: 'ML-DSA-44'
}

export interface Recipe {
  rotate: Rotation
  resize: [number, number] | null
  brightness: number
  contrast: number
}

/** [col0, row0, cols, rows] in tile units. */
export type Crop = [number, number, number, number]

export interface Descriptor {
  v: 1
  manifest_tx: string
  producer: string
  hidden: string
  crop: Crop | null
  recipe: Recipe | null
}

export interface Sidecar {
  velum: 1
  manifest: Manifest
  manifest_sig: string
  authority_pk: string
  manifest_tx: string
  level: Descriptor
  level_tx: string
  visible: [number, string][]
  hidden: [number, string][]
}

export class SidecarError extends Error {
  constructor(
    readonly path: string,
    message: string,
  ) {
    super(`${path}: ${message}`)
    this.name = 'SidecarError'
  }
}

const HEX_LOWER = /^[0-9a-f]*$/
const TX_HASH = /^[0-9A-F]{64}$/

type Obj = Record<string, unknown>

function obj(v: unknown, path: string, keys: string[]): Obj {
  if (typeof v !== 'object' || v === null || Array.isArray(v)) throw new SidecarError(path, 'must be an object')
  const o = v as Obj
  const have = Object.keys(o).sort()
  const want = [...keys].sort()
  const extra = have.filter((k) => !want.includes(k))
  const missing = want.filter((k) => !have.includes(k))
  if (extra.length) throw new SidecarError(path, `unknown key ${extra.map((k) => JSON.stringify(k)).join(', ')}`)
  if (missing.length) throw new SidecarError(path, `missing key ${missing.map((k) => JSON.stringify(k)).join(', ')}`)
  return o
}

function int(v: unknown, path: string, min: number, max: number): number {
  if (typeof v !== 'number' || !Number.isInteger(v)) throw new SidecarError(path, 'must be an integer')
  if (v < min || v > max) throw new SidecarError(path, `must be in ${min}..${max}`)
  return v
}

function hex(v: unknown, path: string, bytes: number): string {
  if (typeof v !== 'string' || !HEX_LOWER.test(v)) throw new SidecarError(path, 'must be lowercase hex')
  if (v.length !== bytes * 2) throw new SidecarError(path, `must be ${bytes} bytes (${bytes * 2} hex digits)`)
  return v
}

function txHash(v: unknown, path: string): string {
  if (typeof v !== 'string' || !TX_HASH.test(v)) throw new SidecarError(path, 'must be a 64-digit UPPERCASE tx hash')
  return v
}

function address(v: unknown, path: string): string {
  if (typeof v !== 'string' || !isClassicAddress(v)) throw new SidecarError(path, 'must be an XRPL classic address')
  return v
}

function exact<T>(v: unknown, path: string, value: T): T {
  if (v !== value) throw new SidecarError(path, `must be ${JSON.stringify(value)}`)
  return value
}

export function parseManifest(v: unknown, path = 'manifest'): Manifest {
  const o = obj(v, path, ['v', 'w', 'h', 'tile', 'root', 'authority', 'pq_alg'])
  const w = int(o.w, `${path}.w`, 1, MAX_SIDE)
  const h = int(o.h, `${path}.h`, 1, MAX_SIDE)
  if (w * h > MAX_PIXELS) throw new SidecarError(path, `image size ${w}x${h} above ${MAX_PIXELS} pixels`) // manifest.py
  return {
    v: exact(o.v, `${path}.v`, 1 as const),
    w,
    h,
    tile: exact(o.tile, `${path}.tile`, TILE as 64),
    root: hex(o.root, `${path}.root`, 32),
    authority: address(o.authority, `${path}.authority`),
    pq_alg: exact(o.pq_alg, `${path}.pq_alg`, 'ML-DSA-44' as const),
  }
}

function parseRecipe(v: unknown, path: string): Recipe | null {
  if (v === null) return null
  const o = obj(v, path, ['rotate', 'resize', 'brightness', 'contrast'])
  const rotate = o.rotate
  if (rotate !== 0 && rotate !== 90 && rotate !== 180 && rotate !== 270) throw new SidecarError(`${path}.rotate`, 'must be 0, 90, 180 or 270')
  let resize: [number, number] | null = null
  if (o.resize !== null) {
    if (!Array.isArray(o.resize) || o.resize.length !== 2) throw new SidecarError(`${path}.resize`, 'must be [w, h] or null')
    resize = [int(o.resize[0], `${path}.resize[0]`, 1, MAX_SIDE), int(o.resize[1], `${path}.resize[1]`, 1, MAX_SIDE)]
  }
  return {
    rotate,
    resize,
    brightness: int(o.brightness, `${path}.brightness`, -255, 255),
    contrast: int(o.contrast, `${path}.contrast`, -255, 255),
  }
}

export function parseDescriptor(v: unknown, path: string, n: number): Descriptor {
  const o = obj(v, path, ['v', 'manifest_tx', 'producer', 'hidden', 'crop', 'recipe'])
  let crop: Crop | null = null
  if (o.crop !== null) {
    if (!Array.isArray(o.crop) || o.crop.length !== 4) throw new SidecarError(`${path}.crop`, 'must be [col0, row0, cols, rows] or null')
    // the same bounds as descriptor.py: a crop that parses but does not fit the grid is a V5 failure
    crop = [0, 1, 2, 3].map((k) => int((o.crop as unknown[])[k], `${path}.crop[${k}]`, 0, MAX_SIDE)) as Crop
  }
  const hidden = hex(o.hidden, `${path}.hidden`, Math.ceil(n / 8))
  bitmapToSet(hidden, n, `${path}.hidden`) // validates trailing bits
  return {
    v: exact(o.v, `${path}.v`, 1 as const),
    manifest_tx: txHash(o.manifest_tx, `${path}.manifest_tx`),
    producer: address(o.producer, `${path}.producer`),
    hidden,
    crop,
    recipe: parseRecipe(o.recipe, `${path}.recipe`),
  }
}

function pairs(v: unknown, path: string, n: number): [number, string][] {
  if (!Array.isArray(v)) throw new SidecarError(path, 'must be an array')
  let last = -1
  return v.map((p, k) => {
    if (!Array.isArray(p) || p.length !== 2) throw new SidecarError(`${path}[${k}]`, 'must be [index, hex]')
    const i = int(p[0], `${path}[${k}][0]`, 0, n - 1)
    if (i <= last) throw new SidecarError(`${path}[${k}]`, 'indices must be strictly increasing')
    last = i
    return [i, hex(p[1], `${path}[${k}][1]`, 32)]
  })
}

/** Parse sidecar text strictly (parseStrictJson, then the schema). Throws CanonicalError or SidecarError. */
export function parseSidecarText(text: string): Sidecar {
  return parseSidecar(parseStrictJson(text))
}

/** Parse an already decoded sidecar value. Throws SidecarError naming the first offending field. */
export function parseSidecar(v: unknown): Sidecar {
  const o = obj(v, '$', ['velum', 'manifest', 'manifest_sig', 'authority_pk', 'manifest_tx', 'level', 'level_tx', 'visible', 'hidden'])
  exact(o.velum, '$.velum', 1)
  const manifest = parseManifest(o.manifest, '$.manifest')
  const n = new Grid(manifest.w, manifest.h).n
  const level = parseDescriptor(o.level, '$.level', n)
  const visible = pairs(o.visible, '$.visible', n)
  const hidden = pairs(o.hidden, '$.hidden', n)
  const seen = new Uint8Array(n)
  for (const [i] of [...visible, ...hidden]) {
    if (seen[i]) throw new SidecarError('$', `tile ${i} is listed as both visible and hidden`)
    seen[i] = 1
  }
  const absent = seen.indexOf(0)
  if (absent !== -1) throw new SidecarError('$', `tile ${absent} is in neither visible nor hidden`)
  return {
    velum: 1,
    manifest,
    manifest_sig: hex(o.manifest_sig, '$.manifest_sig', SIG_BYTES),
    authority_pk: hex(o.authority_pk, '$.authority_pk', PK_BYTES),
    manifest_tx: txHash(o.manifest_tx, '$.manifest_tx'),
    level,
    level_tx: txHash(o.level_tx, '$.level_tx'),
    visible,
    hidden,
  }
}

/** Hidden bitmap (MSB first) to a set of tile indices. Rejects wrong length and set trailing bits. */
export function bitmapToSet(hexStr: string, n: number, path = 'hidden'): Set<number> {
  const bytes = Math.ceil(n / 8)
  if (hexStr.length !== bytes * 2 || !HEX_LOWER.test(hexStr)) throw new SidecarError(path, `must be ${bytes} bytes of lowercase hex`)
  const out = new Set<number>()
  for (let b = 0; b < bytes; b++) {
    const byte = parseInt(hexStr.slice(b * 2, b * 2 + 2), 16)
    for (let bit = 0; bit < 8; bit++) {
      if (byte & (0x80 >> bit)) {
        const i = b * 8 + bit
        if (i >= n) throw new SidecarError(path, 'unused trailing bits must be 0')
        out.add(i)
      }
    }
  }
  return out
}

export function setToBitmap(set: Iterable<number>, n: number): string {
  const bytes = new Uint8Array(Math.ceil(n / 8))
  for (const i of set) {
    if (!Number.isInteger(i) || i < 0 || i >= n) throw new RangeError(`tile ${i} outside 0..${n - 1}`)
    bytes[i >> 3]! |= 0x80 >> (i & 7)
  }
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}

/** Tiles outside a crop rectangle (all of them must be hidden, VELUM.md 6.3 rule 2). */
export function tilesOutsideCrop(grid: Grid, crop: Crop | null): number[] {
  if (!crop) return []
  const [c0, r0, cs, rs] = crop
  const out: number[] = []
  for (let i = 0; i < grid.n; i++) {
    const c = i % grid.cols
    const r = Math.floor(i / grid.cols)
    if (c < c0 || c >= c0 + cs || r < r0 || r >= r0 + rs) out.push(i)
  }
  return out
}

export function cropFits(grid: Grid, crop: Crop): boolean {
  const [c0, r0, cs, rs] = crop
  return cs >= 1 && rs >= 1 && c0 >= 0 && r0 >= 0 && c0 + cs <= grid.cols && r0 + rs <= grid.rows
}
