/**
 * Conformance: velum-js must reproduce every value of the Python reference vectors byte for byte
 * (frontend-spec.md section 7). Read straight from the backend's tests/vectors: one source of truth.
 */
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import {
  PngError,
  SidecarChunkError,
  parseStrictJson,
  readSidecar,
  canonicalString,
  deriveSalt,
  fingerprint,
  fromHex,
  gridOf,
  leafHash,
  merkleRoot,
  readPng,
  sha256,
  tileBytes,
  toHex,
  verify,
  writePng,
  ascii,
  MANIFEST_CTX,
  canonicalBytes,
  floorDiv,
} from '../../lib/velum'

const V = JSON.parse(readFileSync(new URL('../../../tests/vectors/core_v1.json', import.meta.url), 'utf8'))
const PQ = JSON.parse(readFileSync(new URL('../fixtures/mldsa_interop.json', import.meta.url), 'utf8'))
const b64 = (s: string) => new Uint8Array(Buffer.from(s, 'base64'))

describe('vectors file', () => {
  it('is version 1', () => expect(V.version).toBe(1))
})

describe('png decode', () => {
  for (const c of V.png_decode) {
    it(c.name, async () => {
      const img = await readPng(b64(c.png_b64))
      expect([img.width, img.height]).toEqual([c.width, c.height])
      expect(toHex(sha256(img.rgb))).toBe(c.rgb_sha256)
    })
  }
})

describe('png reject', () => {
  for (const c of V.png_reject) {
    it(c.name, async () => {
      await expect(readPng(b64(c.png_b64))).rejects.toBeInstanceOf(PngError)
    })
  }
})

describe('png strict mode (what the verifier reads)', () => {
  for (const c of V.png_verify_reject) {
    it(c.name, async () => {
      await expect(readPng(b64(c.png_b64), { strict: true })).rejects.toBeInstanceOf(PngError)
    })
  }
})

describe('embedded sidecar (zTXt velum.sidecar)', () => {
  for (const c of V.png_sidecar) {
    it(c.name, async () => {
      const bytes = b64(c.png_b64)
      if (c.sidecar === 'ERROR') await expect(readSidecar(bytes)).rejects.toBeInstanceOf(SidecarChunkError)
      else expect(await readSidecar(bytes)).toBe(c.sidecar)
    })
  }
  it('writePng embeds a sidecar that readSidecar returns, and the pixels stay the same', async () => {
    const img = await readPng(b64(V.image_case.png_b64))
    const text = '{"velum":1}\n'
    const png = writePng(img, text)
    expect(await readSidecar(png)).toBe(text)
    const back = await readPng(png, { strict: true })
    expect(toHex(sha256(back.rgb))).toBe(toHex(sha256(img.rgb)))
  })
})

describe('png write', () => {
  it('round-trips and matches the Python writer byte for byte', async () => {
    const ref = V.png_decode.find((c: { name: string }) => c.name === 'velum-writer-uncompressed')
    const bytes = b64(ref.png_b64)
    const img = await readPng(bytes)
    expect(toHex(writePng(img))).toBe(toHex(bytes))
  })
  it('matches the Python writer on the image case', async () => {
    const bytes = b64(V.image_case.png_b64)
    expect(toHex(writePng(await readPng(bytes)))).toBe(toHex(bytes))
  })
})

describe('salts, leaves, Merkle tree', () => {
  const K = fromHex(V.tree.K_hex)
  const zero = new Uint8Array(64 * 64 * 3)
  it('salts', () => V.tree.salts.forEach((s: string, i: number) => expect(toHex(deriveSalt(K, i))).toBe(s)))
  it('leaves', () => V.tree.leaves.forEach((l: string, i: number) => expect(toHex(leafHash(i, deriveSalt(K, i), zero))).toBe(l)))
  it('roots n = 1, 2, 3', () => {
    const leaves = V.tree.leaves.map(fromHex)
    for (const [n, root] of Object.entries(V.tree.roots)) expect(toHex(merkleRoot(leaves.slice(0, Number(n))))).toBe(root)
  })
})

describe('image case (70 x 66, padded edge tiles)', () => {
  it('grid, tiles, leaves and root', async () => {
    const c = V.image_case
    const img = await readPng(b64(c.png_b64))
    const grid = gridOf(img)
    expect([grid.cols, grid.rows]).toEqual([c.cols, c.rows])
    const K = fromHex(c.K_hex)
    const leaves = []
    for (let i = 0; i < grid.n; i++) {
      const tile = tileBytes(img, i)
      expect(toHex(sha256(tile))).toBe(c.tile_sha256[i])
      leaves.push(leafHash(i, deriveSalt(K, i), tile))
    }
    expect(leaves.map(toHex)).toEqual(c.leaves)
    expect(toHex(merkleRoot(leaves))).toBe(c.root)
  })
})

describe('canonical JSON', () => {
  for (const [k, c] of V.canonical_json.entries()) it(`case ${k}`, () => expect(canonicalString(c.value)).toBe(c.canonical))
  it('rejects booleans, floats and escapes', () => {
    expect(() => canonicalString({ a: true })).toThrow()
    expect(() => canonicalString({ a: 1.5 })).toThrow()
    expect(() => canonicalString({ a: 'x"y' })).toThrow()
    expect(() => canonicalString({ a: 'é' })).toThrow()
  })
})

describe('strict JSON (canonical.loads_strict)', () => {
  it('parses what JSON.parse parses for valid input', () => {
    const text = '{"a":[1,-2,{"b":null}],"s":"x y","z":{}}'
    expect(parseStrictJson(text)).toEqual(JSON.parse(text))
  })
  const bad: [string, string][] = [
    ['float', '{"a":1.0}'], ['exponent', '{"a":1e3}'], ['boolean', '{"a":true}'], ['NaN', '{"a":NaN}'],
    ['duplicate key', '{"a":1,"a":2}'], ['too deep', '['.repeat(17) + ']'.repeat(17)], ['very deep', '['.repeat(100000) + ']'.repeat(100000)],
    ['huge integer', '{"a":' + '9'.repeat(5000) + '}'], ['escaped string', '{"a":"x\\u00e9"}'], ['trailing data', '{} {}'], ['unterminated', '{"a":"x'],
  ]
  for (const [name, text] of bad) it(`rejects ${name}`, () => expect(() => parseStrictJson(text)).toThrow())
  it('brackets inside strings do not count as nesting', () => {
    expect(parseStrictJson('{"a":"[[[[[[[[[[[[[[[[[[[[","b":[[1]]}')).toEqual({ a: '['.repeat(20), b: [[1]] })
  })
})

describe('ML-DSA-44 interop with the Python signer', () => {
  const pk = fromHex(PQ.pk_hex)
  const sig = fromHex(PQ.sig_hex)
  const msg = canonicalBytes(PQ.manifest)
  it('canonical manifest bytes match', () => expect(new TextDecoder().decode(msg)).toBe(PQ.message))
  it('fingerprint', () => expect(fingerprint(pk)).toBe(PQ.pk_sha256))
  it('verifies with the right context', () => expect(verify(pk, msg, sig, MANIFEST_CTX)).toBe(true))
  it('fails with another context', () => expect(verify(pk, msg, sig, ascii('VELUM/manifest/v2'))).toBe(false))
  it('fails on a changed message', () => {
    const bad = canonicalBytes({ ...PQ.manifest, h: PQ.manifest.h + 1 })
    expect(verify(pk, bad, sig, MANIFEST_CTX)).toBe(false)
  })
  it('fails on malformed lengths', () => expect(verify(pk.subarray(1), msg, sig, MANIFEST_CTX)).toBe(false))
})

describe('floorDiv', () => {
  it('floors toward -infinity like Python //', () => {
    expect(floorDiv(-7, 2)).toBe(-4)
    expect(floorDiv(7, 2)).toBe(3)
    expect(floorDiv(-8, 2)).toBe(-4)
  })
})
