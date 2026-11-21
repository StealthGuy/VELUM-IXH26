/**
 * PNG reader and writer, decoding in JS (frontend-spec.md 3.1: never read pixels back from a canvas).
 * Mirrors velum/src/velum/png.py.
 *
 * Reader: bit depth 8, colour type 2 (RGB) or 6 (RGBA, every alpha = 255), no interlace, any
 * compression, row filters 0-4, consecutive IDAT, W*H <= 2^25 checked on the header before inflating.
 * With `strict` (what the verifier uses) only tEXt, zTXt, iTXt, tIME may accompany the pixels: APNG,
 * tRNS, colour profiles or eXIf would make a browser show something other than the verified pixels.
 * `maxPixels` is the verifier's budget: above it OverBudget, which says nothing about authenticity.
 * Writer: uncompressed (zlib stored blocks, filter 0 on every row), chunks IHDR, optionally one zTXt
 * "velum.sidecar" carrying the sidecar JSON (VELUM.md section 6), IDAT, IEND.
 */
import { concat } from './bytes'
import { MAX_SIDE, makeImage, type Image } from './image'

const SIGNATURE = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
const COLOR_RGB = 2
const COLOR_RGBA = 6
const STORED_BLOCK_MAX = 65535
export const MAX_PIXELS = 2 ** 25 // 33.5 MP: what a small file may make us inflate (image.py MAX_PIXELS)
export const SIDECAR_KEYWORD = 'velum.sidecar'
export const MAX_SIDECAR = 4 << 20 // bytes once inflated
const DISPLAY_SAFE = new Set(['tEXt', 'zTXt', 'iTXt', 'tIME']) // text and time: never change what a viewer shows

export class PngError extends Error {
  override name = 'PngError'
}

/** The image is valid but above this reader's pixel budget: inconclusive, not a forgery. */
export class OverBudget extends PngError {
  override name = 'OverBudget'
}

/** The PNG is readable but its velum.sidecar chunk is not. Never a reason to use an external file. */
export class SidecarChunkError extends PngError {
  override name = 'SidecarChunkError'
}

export interface ReadOptions {
  strict?: boolean
  maxPixels?: number
}

// ---------------------------------------------------------------- checksums
const CRC_TABLE = (() => {
  const t = new Uint32Array(256)
  for (let n = 0; n < 256; n++) {
    let c = n
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
    t[n] = c >>> 0
  }
  return t
})()

export function crc32(...parts: Uint8Array[]): number {
  let c = 0xffffffff
  for (const p of parts) for (const b of p) c = CRC_TABLE[(c ^ b) & 255]! ^ (c >>> 8)
  return (c ^ 0xffffffff) >>> 0
}

export function adler32(data: Uint8Array): number {
  let a = 1
  let b = 0
  for (let i = 0; i < data.length; ) {
    const end = Math.min(i + 5552, data.length) // largest run before the sums can overflow 2^32
    for (; i < end; i++) {
      a += data[i]!
      b += a
    }
    a %= 65521
    b %= 65521
  }
  return ((b << 16) | a) >>> 0
}

// ---------------------------------------------------------------- reading
export async function readPng(data: Uint8Array, opts: ReadOptions = {}): Promise<Image> {
  const { width, height, colorType, idat } = parseChunks(data, opts)
  const bpp = colorType === COLOR_RGB ? 3 : 4
  const expected = height * (1 + width * bpp) // one filter byte per row
  const raw = await inflateExactly(idat, expected)
  let pixels = unfilter(raw, width, height, bpp)
  if (colorType === COLOR_RGBA) pixels = dropOpaqueAlpha(pixels)
  return makeImage(width, height, pixels)
}

function typeName(t: Uint8Array): string {
  return String.fromCharCode(...t)
}

interface Chunk {
  name: string
  ctype: Uint8Array
  body: Uint8Array
}

/** Every chunk from the signature to IEND, CRCs checked; nothing may follow IEND. */
function walkChunks(data: Uint8Array): Chunk[] {
  if (data.length < 8 || SIGNATURE.some((b, i) => data[i] !== b)) throw new PngError('not a PNG (bad signature)')
  const view = new DataView(data.buffer, data.byteOffset, data.byteLength)
  const out: Chunk[] = []
  let pos = 8
  for (;;) {
    if (pos + 12 > data.length) throw new PngError('truncated chunk')
    const length = view.getUint32(pos)
    if (pos + 12 + length > data.length) throw new PngError('truncated chunk')
    const ctype = data.subarray(pos + 4, pos + 8)
    const body = data.subarray(pos + 8, pos + 8 + length)
    const name = typeName(ctype)
    if (crc32(ctype, body) !== view.getUint32(pos + 8 + length)) throw new PngError(`bad CRC in ${name} chunk`)
    pos += 12 + length
    out.push({ name, ctype, body })
    if (name === 'IEND') break
  }
  if (pos !== data.length) throw new PngError('data after IEND')
  return out
}

function parseChunks(data: Uint8Array, opts: ReadOptions): { width: number; height: number; colorType: number; idat: Uint8Array } {
  let header: { width: number; height: number; colorType: number } | null = null
  const idat: Uint8Array[] = []
  let idatClosed = false // IDAT chunks must be consecutive (PNG spec; libpng and browsers enforce it)
  for (const { name, ctype, body } of walkChunks(data)) {
    if (header === null && name !== 'IHDR') throw new PngError('IHDR must be the first chunk')
    if (name === 'IDAT' && idatClosed) throw new PngError('IDAT chunks are not consecutive')
    if (name !== 'IDAT' && idat.length) idatClosed = true
    if (name === 'IHDR') {
      if (header !== null) throw new PngError('duplicate IHDR')
      header = parseIhdr(body)
      if (opts.maxPixels !== undefined && header.width * header.height > opts.maxPixels) {
        throw new OverBudget(`image is ${header.width}x${header.height}, above this verifier's budget of ${opts.maxPixels} pixels`)
      }
    } else if (name === 'IDAT') {
      idat.push(body)
    } else if (name === 'IEND') {
      // end
    } else if (name === 'PLTE') {
      if (opts.strict) throw new PngError('PLTE chunk not allowed: a viewer may display the image through it')
    } else if (!(ctype[0]! & 0x20)) {
      throw new PngError(`unsupported critical chunk ${name}`)
    } else if (opts.strict && !DISPLAY_SAFE.has(name)) {
      throw new PngError(`${name} chunk not allowed: it can change what a viewer displays (only tEXt, zTXt, iTXt, tIME may be added)`)
    }
  }
  if (header === null || idat.length === 0) throw new PngError('missing IHDR or IDAT')
  return { ...header, idat: concat(...idat) }
}

/**
 * The sidecar JSON embedded in a zTXt chunk "velum.sidecar", or null if there is none.
 * Throws PngError if the bytes are not a readable PNG, SidecarChunkError if the chunk itself is bad
 * (two of them, unknown compression, too large, not ASCII).
 */
export async function readSidecar(data: Uint8Array): Promise<string | null> {
  const key = new TextEncoder().encode(SIDECAR_KEYWORD + '\0')
  const found: string[] = []
  for (const { name, body } of walkChunks(data)) {
    if (name !== 'zTXt' || body.length < key.length || key.some((b, i) => body[i] !== b)) continue
    if (found.length) throw new SidecarChunkError('more than one velum.sidecar chunk') // before inflating it
    const rest = body.subarray(key.length)
    if (rest.length === 0 || rest[0] !== 0) throw new SidecarChunkError('velum.sidecar: unknown compression method')
    let text: Uint8Array
    try {
      text = await inflateAtMost(rest.subarray(1), MAX_SIDECAR)
    } catch (e) {
      throw new SidecarChunkError(`velum.sidecar: ${(e as Error).message}`)
    }
    if (text.some((b) => b > 0x7f)) throw new SidecarChunkError('velum.sidecar is not ASCII')
    found.push(new TextDecoder('ascii').decode(text))
  }
  return found[0] ?? null
}

function parseIhdr(body: Uint8Array): { width: number; height: number; colorType: number } {
  if (body.length !== 13) throw new PngError('bad IHDR length')
  const v = new DataView(body.buffer, body.byteOffset, body.byteLength)
  const width = v.getUint32(0)
  const height = v.getUint32(4)
  const [depth, colorType, compression, filtering, interlace] = [body[8]!, body[9]!, body[10]!, body[11]!, body[12]!]
  if (!(width >= 1 && width <= MAX_SIDE && height >= 1 && height <= MAX_SIDE) || width * height > MAX_PIXELS) {
    throw new PngError(`image size ${width}x${height} outside 1..${MAX_SIDE} per side or above ${MAX_PIXELS} pixels`)
  }
  if (depth !== 8) throw new PngError(`bit depth ${depth} not supported (only 8)`)
  if (colorType !== COLOR_RGB && colorType !== COLOR_RGBA) throw new PngError(`colour type ${colorType} not supported (only RGB or RGBA)`)
  if (compression !== 0 || filtering !== 0) throw new PngError('unknown compression or filter method')
  if (interlace !== 0) throw new PngError('interlaced PNG not supported')
  return { width, height, colorType }
}

/** Inflate at most `limit` bytes: anything longer is refused (no zip bombs). */
async function inflateAtMost(stream: Uint8Array, limit: number): Promise<Uint8Array> {
  const parts: Uint8Array[] = []
  let n = 0
  const reader = new Blob([stream as BlobPart]).stream().pipeThrough(new DecompressionStream('deflate')).getReader()
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      n += value.length
      if (n > limit) {
        await reader.cancel().catch(() => {})
        throw new PngError('compressed text too large')
      }
      parts.push(value)
    }
  } catch (err) {
    if (err instanceof PngError) throw err
    throw new PngError(`corrupt compressed text: ${(err as Error).message || 'zlib error'}`)
  }
  return concat(...parts)
}

/** Inflate the zlib stream, refusing anything but exactly `expected` bytes (no zip bombs). */
async function inflateExactly(stream: Uint8Array, expected: number): Promise<Uint8Array> {
  const out = new Uint8Array(expected)
  let n = 0
  const reader = new Blob([stream as BlobPart]).stream().pipeThrough(new DecompressionStream('deflate')).getReader()
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      if (n + value.length > expected) {
        await reader.cancel().catch(() => {})
        throw new PngError('image data has the wrong size')
      }
      out.set(value, n)
      n += value.length
    }
  } catch (err) {
    if (err instanceof PngError) throw err
    // DecompressionStream rejects truncated streams, trailing junk and a bad Adler-32
    throw new PngError(`corrupt image data: ${(err as Error).message || 'zlib error'}`)
  }
  if (n !== expected) throw new PngError('image data has the wrong size')
  return out
}

/** Undo the per-row PNG filters 0-4 (None, Sub, Up, Average, Paeth). All arithmetic mod 256. */
function unfilter(raw: Uint8Array, width: number, height: number, bpp: number): Uint8Array {
  const stride = width * bpp
  const out = new Uint8Array(height * stride)
  let prev = new Uint8Array(stride) // the row above the first row is all zeros
  let pos = 0
  for (let y = 0; y < height; y++) {
    const ftype = raw[pos]!
    const line = out.subarray(y * stride, (y + 1) * stride)
    line.set(raw.subarray(pos + 1, pos + 1 + stride))
    pos += 1 + stride
    switch (ftype) {
      case 0:
        break
      case 1:
        for (let i = bpp; i < stride; i++) line[i] = (line[i]! + line[i - bpp]!) & 255
        break
      case 2:
        for (let i = 0; i < stride; i++) line[i] = (line[i]! + prev[i]!) & 255
        break
      case 3:
        for (let i = 0; i < stride; i++) {
          const left = i >= bpp ? line[i - bpp]! : 0
          line[i] = (line[i]! + ((left + prev[i]!) >> 1)) & 255
        }
        break
      case 4:
        for (let i = 0; i < stride; i++) {
          const a = i >= bpp ? line[i - bpp]! : 0
          const b = prev[i]!
          const c = i >= bpp ? prev[i - bpp]! : 0
          const p = a + b - c
          const pa = Math.abs(p - a)
          const pb = Math.abs(p - b)
          const pc = Math.abs(p - c)
          const predictor = pa <= pb && pa <= pc ? a : pb <= pc ? b : c
          line[i] = (line[i]! + predictor) & 255
        }
        break
      default:
        throw new PngError(`unknown filter type ${ftype} in row ${y}`)
    }
    prev = line
  }
  return out
}

/** RGBA -> RGB, only if every pixel is fully opaque: otherwise what you see is not what is signed. */
function dropOpaqueAlpha(rgba: Uint8Array): Uint8Array {
  const n = rgba.length / 4
  const rgb = new Uint8Array(n * 3)
  for (let i = 0; i < n; i++) {
    if (rgba[4 * i + 3] !== 255) throw new PngError('transparent pixels are not supported (every alpha must be 255)')
    rgb[3 * i] = rgba[4 * i]!
    rgb[3 * i + 1] = rgba[4 * i + 1]!
    rgb[3 * i + 2] = rgba[4 * i + 2]!
  }
  return rgb
}

// ---------------------------------------------------------------- writing
export function writePng(image: Image, sidecar?: string): Uint8Array {
  const { width, height, rgb } = image
  const stride = width * 3
  const raw = new Uint8Array(height * (1 + stride)) // filter byte 0 on every row
  for (let y = 0; y < height; y++) raw.set(rgb.subarray(y * stride, (y + 1) * stride), y * (1 + stride) + 1)
  const ihdr = new Uint8Array(13)
  const v = new DataView(ihdr.buffer)
  v.setUint32(0, width)
  v.setUint32(4, height)
  ihdr.set([8, COLOR_RGB, 0, 0, 0], 8)
  const parts = [SIGNATURE, chunk('IHDR', ihdr)]
  if (sidecar !== undefined) {
    if (!/^[\x00-\x7f]*$/.test(sidecar)) throw new PngError('the sidecar must be ASCII')
    const key = new TextEncoder().encode(SIDECAR_KEYWORD)
    // zTXt: keyword, NUL, compression method 0 (zlib); stored deflate blocks are a valid zlib stream
    parts.push(chunk('zTXt', concat(key, new Uint8Array([0, 0]), zlibStored(new TextEncoder().encode(sidecar)))))
  }
  parts.push(chunk('IDAT', zlibStored(raw)), chunk('IEND', new Uint8Array(0)))
  return concat(...parts)
}

function chunk(name: string, body: Uint8Array): Uint8Array {
  const out = new Uint8Array(12 + body.length)
  const v = new DataView(out.buffer)
  const ctype = new Uint8Array([...name].map((ch) => ch.charCodeAt(0)))
  v.setUint32(0, body.length)
  out.set(ctype, 4)
  out.set(body, 8)
  v.setUint32(8 + body.length, crc32(ctype, body))
  return out
}

/** A zlib stream made only of uncompressed deflate blocks: header 78 01, blocks, Adler-32. */
function zlibStored(data: Uint8Array): Uint8Array {
  const blocks = Math.max(1, Math.ceil(data.length / STORED_BLOCK_MAX))
  const out = new Uint8Array(2 + blocks * 5 + data.length + 4)
  const v = new DataView(out.buffer)
  out[0] = 0x78
  out[1] = 0x01
  let pos = 2
  let start = 0
  do {
    const block = data.subarray(start, start + STORED_BLOCK_MAX)
    out[pos] = start + STORED_BLOCK_MAX >= data.length ? 1 : 0 // BFINAL on the last block
    v.setUint16(pos + 1, block.length, true)
    v.setUint16(pos + 3, block.length ^ 0xffff, true)
    out.set(block, pos + 5)
    pos += 5 + block.length
    start += STORED_BLOCK_MAX
  } while (start < data.length)
  v.setUint32(pos, adler32(data))
  return out
}
