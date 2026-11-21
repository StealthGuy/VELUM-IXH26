/**
 * XRPL classic address check, as strict as xrpl-py's is_valid_classic_address (schema.address):
 * base58 in the Ripple alphabet, version byte 0x00, a 20-byte account ID and a 4-byte checksum
 * (the first bytes of SHA-256(SHA-256(version ‖ account ID))). A regex alone accepts typos.
 */
import { sha256 } from './hash'

const ALPHABET = 'rpshnaf39wBUDNEGHJKLM4PQRST7VWXYZ2bcdeCg65jkm8oFqi1tuvAxyz'
const SHAPE = /^r[1-9A-HJ-NP-Za-km-z]{24,34}$/ // the Ripple alphabet has the same 58 characters as Bitcoin's

export function isClassicAddress(s: string): boolean {
  if (!SHAPE.test(s)) return false
  let n = 0n
  for (const c of s) n = n * 58n + BigInt(ALPHABET.indexOf(c))
  const body: number[] = []
  for (; n > 0n; n >>= 8n) body.unshift(Number(n & 0xffn))
  let zeros = 0
  while (s[zeros] === ALPHABET[0]) zeros++ // each leading 'r' encodes one zero byte
  const bytes = new Uint8Array([...new Array<number>(zeros).fill(0), ...body])
  if (bytes.length !== 25 || bytes[0] !== 0) return false
  const check = sha256(sha256(bytes.subarray(0, 21)))
  return check.subarray(0, 4).every((b, i) => b === bytes[21 + i])
}
