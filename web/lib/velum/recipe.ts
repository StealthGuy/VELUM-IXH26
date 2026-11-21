/**
 * Rendition recipe (VELUM.md section 6.4): crop, rotate, resize by exact area averaging,
 * brightness / contrast. Integers only; `//` is floor division as in Python.
 */
import { floorDiv } from './bytes'
import { type Image, makeImage } from './image'
import type { Crop, Recipe, Rotation } from './sidecar'
import { Grid, TILE } from './tiles'

export class RecipeError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'RecipeError'
  }
}

export function crop(img: Image, c: Crop): Image {
  const grid = new Grid(img.width, img.height)
  const [c0, r0, cs, rs] = c
  if (!(cs >= 1 && rs >= 1 && c0 >= 0 && r0 >= 0 && c0 + cs <= grid.cols && r0 + rs <= grid.rows)) {
    throw new RecipeError(`crop ${JSON.stringify(c)} is outside the ${grid.cols}x${grid.rows} tile grid`)
  }
  const x0 = c0 * TILE
  const y0 = r0 * TILE
  const w = Math.min(cs * TILE, img.width - x0)
  const h = Math.min(rs * TILE, img.height - y0)
  const out = new Uint8Array(w * h * 3)
  for (let y = 0; y < h; y++) {
    const s = ((y0 + y) * img.width + x0) * 3
    out.set(img.rgb.subarray(s, s + w * 3), y * w * 3)
  }
  return makeImage(w, h, out)
}

export function rotate(img: Image, deg: Rotation): Image {
  if (deg === 0) return img
  const { width: w, height: h, rgb } = img
  const ow = deg === 180 ? w : h
  const oh = deg === 180 ? h : w
  const out = new Uint8Array(ow * oh * 3)
  for (let r = 0; r < oh; r++) {
    for (let c = 0; c < ow; c++) {
      let sy: number, sx: number
      if (deg === 90) [sy, sx] = [h - 1 - c, r]
      else if (deg === 180) [sy, sx] = [h - 1 - r, w - 1 - c]
      else [sy, sx] = [c, w - 1 - r]
      const s = (sy * w + sx) * 3
      const d = (r * ow + c) * 3
      out[d] = rgb[s]!
      out[d + 1] = rgb[s + 1]!
      out[d + 2] = rgb[s + 2]!
    }
  }
  return makeImage(ow, oh, out)
}

/** For each output index, the source indices and integer weights covering it. Weights sum to nIn. */
function weights(nIn: number, nOut: number): { start: number; w: number[] }[] {
  const out: { start: number; w: number[] }[] = []
  for (let X = 0; X < nOut; X++) {
    const lo = X * nIn
    const hi = (X + 1) * nIn
    const start = Math.floor(lo / nOut)
    const w: number[] = []
    for (let x = start; x * nOut < hi; x++) {
      w.push(Math.max(0, Math.min((x + 1) * nOut, hi) - Math.max(x * nOut, lo)))
    }
    out.push({ start, w })
  }
  return out
}

export function resize(img: Image, wOut: number, hOut: number): Image {
  const { width: wIn, height: hIn, rgb } = img
  if (!(Number.isInteger(wOut) && Number.isInteger(hOut) && wOut >= 1 && hOut >= 1 && wOut <= wIn && hOut <= hIn)) {
    throw new RecipeError(`resize to ${wOut}x${hOut} must be between 1x1 and ${wIn}x${hIn} (no upscaling)`)
  }
  if (wOut === wIn && hOut === hIn) return img
  const wx = weights(wIn, wOut)
  const wy = weights(hIn, hOut)
  // Separable and exact: horizontal integer sums first, then vertical. Max sum 255*wIn*hIn < 2^53.
  const rowSums = new Float64Array(hIn * wOut * 3)
  for (let y = 0; y < hIn; y++) {
    for (let X = 0; X < wOut; X++) {
      const { start, w } = wx[X]!
      let r = 0, g = 0, b = 0
      for (let k = 0; k < w.length; k++) {
        const s = (y * wIn + start + k) * 3
        const f = w[k]!
        r += f * rgb[s]!
        g += f * rgb[s + 1]!
        b += f * rgb[s + 2]!
      }
      const d = (y * wOut + X) * 3
      rowSums[d] = r
      rowSums[d + 1] = g
      rowSums[d + 2] = b
    }
  }
  const D = wIn * hIn
  const half = Math.floor(D / 2)
  const out = new Uint8Array(wOut * hOut * 3)
  for (let Y = 0; Y < hOut; Y++) {
    const { start, w } = wy[Y]!
    for (let X = 0; X < wOut; X++) {
      let r = 0, g = 0, b = 0
      for (let k = 0; k < w.length; k++) {
        const s = ((start + k) * wOut + X) * 3
        const f = w[k]!
        r += f * rowSums[s]!
        g += f * rowSums[s + 1]!
        b += f * rowSums[s + 2]!
      }
      const d = (Y * wOut + X) * 3
      out[d] = Math.floor((r + half) / D)
      out[d + 1] = Math.floor((g + half) / D)
      out[d + 2] = Math.floor((b + half) / D)
    }
  }
  return makeImage(wOut, hOut, out)
}

export function adjustLut(brightness: number, contrast: number): Uint8Array {
  const lut = new Uint8Array(256)
  for (let v = 0; v < 256; v++) {
    const x = floorDiv((v - 128) * (256 + contrast) + 128 * 256 + brightness * 256 + 128, 256)
    lut[v] = Math.max(0, Math.min(255, x))
  }
  return lut
}

export function adjust(img: Image, brightness: number, contrast: number): Image {
  if (brightness === 0 && contrast === 0) return img
  const lut = adjustLut(brightness, contrast)
  const out = new Uint8Array(img.rgb.length)
  for (let k = 0; k < out.length; k++) out[k] = lut[img.rgb[k]!]!
  return makeImage(img.width, img.height, out)
}

/** The full public recipe, in the order of VELUM.md 6.4. */
export function applyRecipe(evidence: Image, c: Crop | null, recipe: Recipe | null): Image {
  let img = c ? crop(evidence, c) : evidence
  if (recipe) {
    img = rotate(img, recipe.rotate)
    if (recipe.resize) img = resize(img, recipe.resize[0], recipe.resize[1])
    img = adjust(img, recipe.brightness, recipe.contrast)
  }
  return img
}

/** Size of the rendition; throws RecipeError if the crop or the recipe cannot be applied (V5). */
export function outputSize(width: number, height: number, c: Crop | null, recipe: Recipe | null): [number, number] {
  let w = width
  let h = height
  if (c) {
    const grid = new Grid(width, height)
    const [c0, r0, cs, rs] = c
    if (!(cs >= 1 && rs >= 1 && c0 >= 0 && r0 >= 0 && c0 + cs <= grid.cols && r0 + rs <= grid.rows)) {
      throw new RecipeError(`crop ${JSON.stringify(c)} is outside the ${grid.cols}x${grid.rows} tile grid`)
    }
    w = Math.min(cs * TILE, width - c0 * TILE)
    h = Math.min(rs * TILE, height - r0 * TILE)
  }
  if (recipe) {
    if (recipe.rotate === 90 || recipe.rotate === 270) [w, h] = [h, w]
    if (recipe.resize) {
      if (!(recipe.resize[0] <= w && recipe.resize[1] <= h)) {
        throw new RecipeError(`recipe resizes ${w}x${h} to ${recipe.resize[0]}x${recipe.resize[1]}: only shrinking is allowed`)
      }
      ;[w, h] = recipe.resize
    }
  }
  return [w, h]
}
