// Copy the Python demo (make demo -> ../out/demo, live Testnet anchors) into the Viewer's samples, and
// the demo trust list (../trust.local.json, public data only: address and ML-DSA key hash) into
// trust-list.json. No faucet, no transactions, no ledger data invented: the samples verify against
// the real Testnet, like any other file.
import { copyFileSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const web = join(dirname(fileURLToPath(import.meta.url)), '..')
const demo = join(web, '..', 'out', 'demo')
const out = join(web, 'public', 'samples')
const trustSrc = join(web, '..', 'trust.local.json')

for (const f of [join(demo, 'l2.png'), trustSrc]) {
  if (!existsSync(f)) {
    console.error(`missing ${f}: run "make demo" in the repository root first`)
    process.exit(1)
  }
}

const samples = [
  { id: 'pizza-l0', level: 'L0', label: 'Original, signed by the authority (for the judges)', files: { evidence: ['l0.png', 'case.png'] } },
  { id: 'pizza-l1', level: 'L1', label: 'Lab hid the password card (for analysts)', files: { evidence: ['l1.png', 'case.png'] } },
  { id: 'pizza-l2', level: 'L2', label: 'Newsroom hid the suspect and shrank it (for the public)', files: { evidence: ['l2.png', 'case.png'], rendition: ['l2.public.png', 'case.public.png'] } },
  { id: 'pizza-unmasked', level: 'Attack', label: "Forgery: the suspect's face pasted back", files: { evidence: ['attack_suspect_unmasked.png', 'case.png'] } },
  { id: 'pizza-restored', level: 'Attack', label: 'Forgery: a pizza painted into the public image', files: { evidence: ['l2.png', 'case.png'], rendition: ['attack_pizza_restored.public.png', 'case.public.png'] } },
]

rmSync(out, { recursive: true, force: true })
const index = { network: 'testnet', created: new Date().toISOString(), source: 'make demo (scripts/demo_pizza.py)', samples: [] }
for (const s of samples) {
  mkdirSync(join(out, s.id), { recursive: true })
  const files = {}
  for (const [role, [from, to]] of Object.entries(s.files)) {
    copyFileSync(join(demo, from), join(out, s.id, to))
    files[role] = to
  }
  index.samples.push({ id: s.id, level: s.level, label: s.label, files })
}
writeFileSync(join(out, 'index.json'), JSON.stringify(index, null, 1) + '\n')

const entries = JSON.parse(readFileSync(trustSrc, 'utf8')).map((e) => ({
  name: e.name, network: e.network, xrpl_address: e.xrpl_address, mldsa44_pk_sha256: e.mldsa44_pk_sha256, not_after: e.not_after ?? null,
}))
writeFileSync(join(web, 'trust-list.json'), JSON.stringify({ version: 'demo', entries }, null, 1) + '\n')
console.log(`${samples.length} samples in public/samples, ${entries.length} authority in trust-list.json`)
