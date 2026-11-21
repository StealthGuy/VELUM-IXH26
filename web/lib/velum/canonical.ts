/**
 * Canonical JSON (VELUM.md section 5). Mirrors velum/src/velum/canonical.py.
 * Allowed values: printable-ASCII strings without `"` or `\`, integers, null, arrays and objects of
 * the same. No floats, no booleans. Keys sorted by byte value, no whitespace. Anything else throws.
 */
import { ascii } from './bytes'

export class CanonicalError extends Error {
  override name = 'CanonicalError'
}

export function canonicalBytes(value: unknown): Uint8Array {
  return ascii(canonicalString(value))
}

export function canonicalString(value: unknown, path = '$'): string {
  if (value === null) return 'null'
  if (typeof value === 'boolean') throw new CanonicalError(`${path}: booleans are not allowed`)
  if (typeof value === 'number') {
    if (!Number.isSafeInteger(value)) throw new CanonicalError(`${path}: only safe integers are allowed`)
    return Object.is(value, -0) ? '0' : String(value)
  }
  if (typeof value === 'string') {
    checkText(value, path)
    return `"${value}"`
  }
  if (Array.isArray(value)) return `[${value.map((v, k) => canonicalString(v, `${path}[${k}]`)).join(',')}]`
  if (typeof value === 'object' && Object.getPrototypeOf(value) === Object.prototype) {
    const keys = Object.keys(value)
    for (const key of keys) checkText(key, `${path} key`)
    keys.sort() // ASCII-only keys: UTF-16 code unit order equals byte order
    return `{${keys.map((k) => `"${k}":${canonicalString((value as Record<string, unknown>)[k], `${path}.${k}`)}`).join(',')}}`
  }
  throw new CanonicalError(`${path}: ${typeof value} is not allowed`)
}

function checkText(text: string, path: string): void {
  // printable ASCII only: no escapes, so every JSON encoder writes the same bytes
  if (!/^[\x20-\x7e]*$/.test(text) || text.includes('"') || text.includes('\\')) {
    throw new CanonicalError(`${path}: strings must be printable ASCII without quotes or backslashes`)
  }
}

// ---------------------------------------------------------------- strict parsing (VELUM.md 6.2)
export const MAX_DEPTH = 16 // VELUM documents nest at most 4 levels; deeper is hostile, not a sidecar

/**
 * Parse JSON the way the Python reference does (canonical.loads_strict): integers only (a token like
 * 1.0 or 1e3 is an error, which JSON.parse cannot see), no booleans, no NaN, no duplicate keys, at most
 * MAX_DEPTH levels of nesting, and only values canonical JSON allows. Throws CanonicalError.
 */
export function parseStrictJson(text: string): unknown {
  let pos = 0
  const fail = (msg: string): never => {
    throw new CanonicalError(`${msg} at position ${pos}`)
  }
  const ws = () => {
    while (pos < text.length && ' \t\n\r'.includes(text[pos]!)) pos++
  }
  const value = (depth: number): unknown => {
    ws()
    const ch = text[pos]
    if (ch === '{' || ch === '[') {
      if (depth >= MAX_DEPTH) fail(`JSON nested deeper than ${MAX_DEPTH} levels`)
      return ch === '{' ? object(depth + 1) : array(depth + 1)
    }
    if (ch === '"') return string()
    if (ch === '-' || (ch !== undefined && ch >= '0' && ch <= '9')) return number()
    if (text.startsWith('null', pos)) {
      pos += 4
      return null
    }
    if (text.startsWith('true', pos) || text.startsWith('false', pos)) fail('booleans are not allowed')
    return fail('unexpected character')
  }
  const object = (depth: number): Record<string, unknown> => {
    pos++
    const out: Record<string, unknown> = Object.create(null)
    ws()
    if (text[pos] === '}') {
      pos++
      return { ...out }
    }
    for (;;) {
      ws()
      if (text[pos] !== '"') fail('expected a string key')
      const key = string()
      if (Object.prototype.hasOwnProperty.call(out, key)) fail(`duplicate key ${JSON.stringify(key)}`)
      ws()
      if (text[pos++] !== ':') fail('expected ":"')
      out[key] = value(depth)
      ws()
      const sep = text[pos++]
      if (sep === '}') return { ...out }
      if (sep !== ',') fail('expected "," or "}"')
    }
  }
  const array = (depth: number): unknown[] => {
    pos++
    const out: unknown[] = []
    ws()
    if (text[pos] === ']') {
      pos++
      return out
    }
    for (;;) {
      out.push(value(depth))
      ws()
      const sep = text[pos++]
      if (sep === ']') return out
      if (sep !== ',') fail('expected "," or "]"')
    }
  }
  const string = (): string => {
    const start = pos++
    for (;;) {
      if (pos >= text.length) fail('unterminated string')
      const c = text[pos]!
      if (c === '\\') pos += 2 // skip the escaped character, whatever it is
      else if (c === '"') break
      else pos++
    }
    pos++
    try {
      return JSON.parse(text.slice(start, pos)) as string // decodes the escapes of this one token
    } catch {
      return fail('malformed string')
    }
  }
  const number = (): number => {
    const m = /^-?(0|[1-9][0-9]*)/.exec(text.slice(pos))
    if (!m) return fail('malformed number')
    const next = text[pos + m[0].length]
    if (next === '.' || next === 'e' || next === 'E') fail(`number is not an integer`)
    pos += m[0].length
    const n = Number(m[0])
    if (!Number.isSafeInteger(n)) fail('integer too large')
    return n
  }
  const result = value(0)
  ws()
  if (pos !== text.length) fail('trailing data after JSON')
  canonicalString(result) // the same value checks as canonical JSON (printable ASCII strings...)
  return result
}
