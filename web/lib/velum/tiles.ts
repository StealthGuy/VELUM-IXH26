/**
 * Tile grid, salts and leaf hashes (VELUM.md sections 3 and 4). Mirrors velum/src/velum/tiles.py.
 *
 *   salt_i = HMAC-SHA256(K, "VELUM/salt/v1" || u32be(i))
 *   d_i    = "VELUM/leaf/v1" || u32be(i) || salt_i || tile_i        (tile_i zero padded to 64x64)
 *   leaf_i = SHA256(0x00 || d_i)
 */
import { ascii, concat, u32be } from './bytes'
import { hmacSha256, sha256 } from './hash'
import type { Image } from './image'

export const TILE = 64
export const TILE_BYTES = TILE * TILE * 3 // 12 288
export const SALT_BYTES = 32
const LEAF_TAG = ascii('VELUM/leaf/v1')
const SALT_TAG = ascii('VELUM/salt/v1')
const LEAF_PREFIX = new Uint8Array([0x00])

/** The 64-pixel grid over a W x H image. Tile i = row * cols + col. */
export class Grid {
  constructor(
    readonly width: number,
    readonly height: number,
  ) {}

  get cols(): number {
    return Math.ceil(this.width / TILE)
  }

  get rows(): number {
    return Math.ceil(this.height / TILE)
  }

  get n(): number {
    return this.cols * this.rows
  }

  /** [x0, y0, w, h] of the *real* pixels of tile i; edge tiles are smaller than 64 x 64. */
  rect(i: number): [number, number, number, number] {
    if (!Number.isInteger(i) || i < 0 || i >= this.n) throw new RangeError(`tile ${i} outside 0..${this.n - 1}`)
    const x0 = (i % this.cols) * TILE
    const y0 = Math.floor(i / this.cols) * TILE
    return [x0, y0, Math.min(TILE, this.width - x0), Math.min(TILE, this.height - y0)]
  }
}

export function gridOf(image: Image): Grid {
  return new Grid(image.width, image.height)
}

/** The 64 x 64 x 3 bytes of tile i. Padding is always zero, synthesised here, never read from a file. */
export function tileBytes(image: Image, i: number): Uint8Array {
  const [x0, y0, w, h] = gridOf(image).rect(i)
  const out = new Uint8Array(TILE_BYTES) // zero-filled: padding comes for free
  for (let y = 0; y < h; y++) {
    const start = ((y0 + y) * image.width + x0) * 3
    out.set(image.rgb.subarray(start, start + w * 3), y * TILE * 3)
  }
  return out
}

export function deriveSalt(secret: Uint8Array, i: number): Uint8Array {
  if (secret.length !== 32) throw new RangeError('salt secret K must be 32 bytes')
  return hmacSha256(secret, concat(SALT_TAG, u32be(i)))
}

/** leaf_i = SHA256(0x00 || "VELUM/leaf/v1" || u32be(i) || salt || tile). */
export function leafHash(i: number, salt: Uint8Array, tile: Uint8Array): Uint8Array {
  if (salt.length !== SALT_BYTES || tile.length !== TILE_BYTES) throw new RangeError('bad salt or tile length')
  return sha256(LEAF_PREFIX, LEAF_TAG, u32be(i), salt, tile)
}

/** True if every real pixel of tile i is (0, 0, 0): required for a hidden tile (V3). */
export function tileIsBlack(image: Image, i: number): boolean {
  const [x0, y0, w, h] = gridOf(image).rect(i)
  for (let y = 0; y < h; y++) {
    const start = ((y0 + y) * image.width + x0) * 3
    for (let k = start; k < start + w * 3; k++) if (image.rgb[k] !== 0) return false
  }
  return true
}
