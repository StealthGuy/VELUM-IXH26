/**
 * Derive a more redacted copy from a level (producer role, VELUM.md 6.3), like level.from_level and
 * level.release_level in the Python reference. Newly hidden tiles: pixels painted black, salt replaced
 * by the leaf hash and dropped. Only from evidence + sidecar; black can only be added.
 */
import { fromHex, toHex } from './bytes'
import { type Image, makeImage } from './image'
import { applyRecipe, outputSize } from './recipe'
import { type Crop, type Descriptor, type Recipe, type Sidecar, bitmapToSet, cropFits, setToBitmap, tilesOutsideCrop } from './sidecar'
import { Grid, leafHash, tileBytes } from './tiles'

export interface DerivedLevel {
  evidence: Image
  rendition: Image
  /** What the producer anchors (memo velum/level = SHA-256 of its canonical JSON). */
  descriptor: Descriptor
  /** The new sidecar without its level; finish with withAnchor() once the tx is validated. */
  draft: Omit<Sidecar, 'level' | 'level_tx'>
  /** Tiles hidden here and visible in the source. */
  added: number[]
}

export function deriveLevel(args: {
  source: Sidecar
  evidence: Image
  hide: Iterable<number>
  crop: Crop | null
  recipe: Recipe | null
  producer: string
}): DerivedLevel {
  const { source, evidence, producer } = args
  const grid = new Grid(source.manifest.w, source.manifest.h)
  if (evidence.width !== grid.width || evidence.height !== grid.height) throw new Error('evidence size does not match the manifest')
  const sourceHidden = bitmapToSet(source.level.hidden, grid.n)
  const hidden = new Set<number>(sourceHidden)
  for (const i of args.hide) {
    if (!(Number.isInteger(i) && i >= 0 && i < grid.n)) throw new Error(`tile ${i} is not in the ${grid.n}-tile grid`)
    hidden.add(i)
  }
  if (args.crop) {
    if (!cropFits(grid, args.crop)) throw new Error('crop is outside the tile grid')
    for (const i of tilesOutsideCrop(grid, args.crop)) hidden.add(i)
  }
  const recipe = args.recipe && (args.recipe.rotate || args.recipe.resize || args.recipe.brightness || args.recipe.contrast) ? args.recipe : null
  outputSize(grid.width, grid.height, args.crop, recipe) // throws RecipeError before anything is anchored
  const added = [...hidden].filter((i) => !sourceHidden.has(i)).sort((a, b) => a - b)
  const salts = new Map(source.visible)
  const leaves = new Map(source.hidden)
  for (const i of added) {
    const salt = salts.get(i)
    if (!salt) throw new Error(`tile ${i} has no salt in the source sidecar`)
    leaves.set(i, toHex(leafHash(i, fromHex(salt), tileBytes(evidence, i)))) // before painting black
    salts.delete(i)
  }
  const rgb = new Uint8Array(evidence.rgb)
  for (const i of added) {
    const [x0, y0, w, h] = grid.rect(i)
    for (let y = 0; y < h; y++) rgb.fill(0, ((y0 + y) * grid.width + x0) * 3, ((y0 + y) * grid.width + x0 + w) * 3)
  }
  const newEvidence = makeImage(grid.width, grid.height, rgb)
  const descriptor: Descriptor = {
    v: 1,
    manifest_tx: source.manifest_tx,
    producer,
    hidden: setToBitmap(hidden, grid.n),
    crop: args.crop,
    recipe,
  }
  const byIndex = (a: [number, string], b: [number, string]) => a[0] - b[0]
  const { level: _level, level_tx: _tx, ...rest } = source
  return {
    evidence: newEvidence,
    rendition: applyRecipe(newEvidence, args.crop, recipe),
    descriptor,
    added,
    draft: { ...rest, visible: [...salts.entries()].sort(byIndex), hidden: [...leaves.entries()].sort(byIndex) },
  }
}

export function withAnchor(level: DerivedLevel, tx: string): Sidecar {
  return { ...level.draft, level: level.descriptor, level_tx: tx.toUpperCase() }
}

function sortKeys(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(sortKeys)
  if (v && typeof v === 'object') {
    return Object.fromEntries(Object.keys(v).sort().map((k) => [k, sortKeys((v as Record<string, unknown>)[k])]))
  }
  return v
}

/** The sidecar text: sorted keys, 1-space indent, final newline. Byte-identical to Sidecar.to_text(). */
export function sidecarJson(sc: Sidecar): string {
  return JSON.stringify(sortKeys(sc), null, 1) + '\n'
}
