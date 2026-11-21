/** Trust list (VELUM.md section 2, frontend-spec.md 3.4). Shipped with the build, never read from input. */
import { isClassicAddress } from './address'

export interface TrustEntry {
  name: string
  network: string
  xrpl_address: string
  mldsa44_pk_sha256: string
  not_after: string | null
}

export interface TrustList {
  version: string
  entries: TrustEntry[]
}

const KEYS = ['mldsa44_pk_sha256', 'name', 'network', 'not_after', 'xrpl_address']
const PK_SHA256 = /^[0-9a-f]{64}$/
const TIME = /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$/

/** As strict as trust.py parse_trust_list: one bad or duplicate entry makes the whole list invalid. */
export function parseTrustList(value: unknown): TrustList {
  const fail = (where: string, why: string): never => { throw new Error(`trust list ${where}: ${why}`) }
  if (typeof value !== 'object' || value === null || Array.isArray(value)) fail('', 'must be an object')
  const { version, entries } = value as { version?: unknown, entries?: unknown }
  if (typeof version !== 'string') fail('version', 'must be a string')
  if (!Array.isArray(entries)) fail('entries', 'must be an array')
  const out: TrustEntry[] = []
  for (const [k, e] of (entries as unknown[]).entries()) {
    const where = `entries[${k}]`
    if (typeof e !== 'object' || e === null || Array.isArray(e)) fail(where, 'must be an object')
    const o = e as Record<string, unknown>
    if (Object.keys(o).sort().join() !== KEYS.join()) fail(where, `must have exactly the keys ${KEYS.join(', ')}`)
    if (typeof o.name !== 'string' || typeof o.network !== 'string') fail(where, 'name and network must be strings')
    if (typeof o.xrpl_address !== 'string' || !isClassicAddress(o.xrpl_address)) fail(where, 'xrpl_address must be a classic address')
    if (typeof o.mldsa44_pk_sha256 !== 'string' || !PK_SHA256.test(o.mldsa44_pk_sha256)) fail(where, 'mldsa44_pk_sha256 must be 64 lowercase hex')
    if (o.not_after !== null && (typeof o.not_after !== 'string' || !TIME.test(o.not_after) || Number.isNaN(Date.parse(o.not_after)))) {
      fail(where, 'not_after must be YYYY-MM-DDTHH:MM:SSZ or null')
    }
    const entry = o as unknown as TrustEntry
    if (findAuthority({ version: '', entries: out }, entry.network, entry.xrpl_address, entry.mldsa44_pk_sha256)) {
      fail(where, `duplicate entry for ${entry.xrpl_address} and this key on ${entry.network}`) // revocation would depend on order
    }
    out.push(entry)
  }
  return { version: version as string, entries: out }
}

/** The entry for this key on this network: the same address and key may be listed for several networks. */
export function findAuthority(list: TrustList, network: string, address: string, pkSha256: string): TrustEntry | null {
  return list.entries.find((e) => e.network === network && e.xrpl_address === address && e.mldsa44_pk_sha256 === pkSha256) ?? null
}

export function findByAddress(list: TrustList, address: string): TrustEntry | null {
  return list.entries.find((e) => e.xrpl_address === address) ?? null
}
