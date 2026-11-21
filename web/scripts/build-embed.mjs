/**
 * Builds the embed widget into public/embed/v1/:
 *   velum-embed.js         classic script, badge only (loaded on every publisher page)
 *   velum-embed-verify.js  ES module, verifier + trust list (fetched on first click)
 */
import { build } from 'esbuild'
import { gzipSync } from 'node:zlib'
import { readFileSync } from 'node:fs'

const out = 'public/embed/v1'
const common = { bundle: true, minify: true, target: 'es2022', legalComments: 'none', logLevel: 'warning' }
await build({ ...common, entryPoints: ['embed/velum-embed.ts'], outfile: `${out}/velum-embed.js`, format: 'iife' })
await build({ ...common, entryPoints: ['embed/verify-entry.ts'], outfile: `${out}/velum-embed-verify.js`, format: 'esm' })
for (const f of ['velum-embed.js', 'velum-embed-verify.js']) {
  const b = readFileSync(`${out}/${f}`)
  console.log(`${f.padEnd(24)} ${(b.length / 1024).toFixed(1).padStart(6)} KB · ${(gzipSync(b).length / 1024).toFixed(1).padStart(5)} KB gzip`)
}
