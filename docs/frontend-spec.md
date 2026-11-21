# VELUM frontend specification

Audience: the frontend developer. Status: **v0.5**, matching backend build step 3 (offline core and
live XRPL layer done). File formats are **frozen at version 1** (`"velum": 1` in every sidecar) and backed by
conformance vectors; any future change bumps that number. The design is
[`VELUM.md`](VELUM.md); this document says what the browser has to do with it.

## 0. Read this first

- The **Python package is the reference implementation**. The browser code is a second, independent
  implementation of the *verifier* and of the *producer* (redaction) role. Wherever they disagree,
  the Python output and its test vectors are right.
- The frontend **never holds secrets**: no XRPL seeds, no ML-DSA keys, no authority master. The
  authority signs images with the CLI only. Anchoring from the browser goes through a wallet extension.
- There is **no VELUM backend**. Everything is static files plus public XRPL nodes (several, with a
  quorum: section 3.3). Images and sidecars
  are hosted by whoever publishes them.

## 1. Deliverables

| # | Product | Who uses it | Does |
|---|---|---|---|
| A | **Viewer** (web app) | anyone | Loads a VELUM image, verifies it fully in the browser, shows the result, the redaction mask, and who published the copy and when |
| B | **Editor** (web app) | producers: labs, newsrooms, anyone holding a copy | Opens a level, blacks out more tiles, crops, applies the public recipe, exports the new level and anchors it on XRPL via a wallet |
| C | **Embed widget** (one JS file) | any website | Adds a small "Verify" badge to VELUM images; one click verifies, a link opens the full report in the Viewer |

A and B can be one app with two modes. All three share one library (section 3).

## 2. Domain model in one page

- The **authority** splits an RGB image into **64×64 tiles** (edge tiles zero-padded; padding is never
  stored, the hasher synthesises it), computes a **salted hash per tile**, builds an **RFC 6962 Merkle
  tree**, and signs a small JSON **manifest** (`w`, `h`, `root`, authority address) with **ML-DSA-44**.
  The authority's XRPL account anchors the manifest.
- A **level** is one redacted copy, in three files:
  - `NAME.png`: the **evidence image**, full frame, hidden tiles painted black;
  - the **sidecar** (2.1) is embedded in `NAME.png` (zTXt `velum.sidecar`), so the PNG alone is enough;
    `NAME.velum.json` is the same sidecar as a separate file, used only when the PNG has none (channels
    that strip metadata);
  - `NAME.public.png` (optional): the **rendition**, the evidence after the level's public recipe (crop,
    rotate by 90° steps, downscale, brightness, contrast). This is the picture people publish.
- Each level is anchored on XRPL **by the account that produced it** (memo `velum/level`, data
  `SHA256(canonical(descriptor))`). A level says **who published it and when**; it does **not** carry
  the history of earlier copies (there is no chain of custody in v1).
- Anyone holding a level can make a **more redacted** one. Nobody can make a less redacted one: the salt
  of a hidden tile is not in the sidecar, so the tile cannot be shown again.

### 2.1 Sidecar (`VELUM.md` §6.2)

```json
{
  "velum": 1,
  "manifest": { "authority": "r…", "h": 720, "pq_alg": "ML-DSA-44", "root": "<64 hex>", "tile": 64, "v": 1, "w": 1280 },
  "manifest_sig": "<hex, 2420 bytes>",
  "authority_pk": "<hex, 1312 bytes>",
  "manifest_tx": "<64 UPPERCASE hex>",
  "level": {
    "v": 1,
    "manifest_tx": "<same as above>",
    "producer": "r… (the account that anchors this level)",
    "hidden": "<bitmap hex, ceil(n/8) bytes, MSB first>",
    "crop": [col0, row0, cols, rows] | null,
    "recipe": { "rotate": 0|90|180|270, "resize": [w, h] | null, "brightness": -255..255, "contrast": -255..255 } | null
  },
  "level_tx": "<64 UPPERCASE hex>",
  "visible": [[0, "<salt hex>"], [1, "<salt hex>"], …],
  "hidden":  [[37, "<leaf hash hex>"], …]
}
```

- **Strict parsing** (all are errors): unknown, missing or duplicate keys; uppercase hex where lowercase
  is required (everything except tx hashes); wrong lengths; booleans; **any number not written as an
  integer** (`1.0`, `1e3`; see 7); `visible`/`hidden` not sorted by strictly increasing index; a tile
  index missing or listed twice (a hidden tile with a salt is exactly that).
- **Bitmap:** tile `i` is bit `7 − (i mod 8)` of byte `i div 8`. Example: n = 10, tiles 0 and 9 hidden →
  `"8040"`. Bits beyond `n − 1` must be 0.
- The descriptor is hashed in **canonical JSON** (`VELUM.md` §5): keys sorted by byte value, no
  whitespace, strings printable ASCII without `"` or `\`, integers only. `JSON.stringify` does **not**
  sort keys: write a small canonical serialiser.

## 3. Shared library: `velum-js`

TypeScript, ES modules, runs in the browser main thread and in Web Workers.

| Module | Responsibility | Notes |
|---|---|---|
| `png` | decode PNG bytes to RGB8 pixels; encode uncompressed PNG | **Own decoder.** See 3.1 |
| `tiles` | grid, padding, tile extraction, leaf hash | `SHA256(0x00 ‖ "VELUM/leaf/v1" ‖ u32be(i) ‖ salt ‖ tile)` (`VELUM.md` §4) |
| `merkle` | RFC 6962 root | hidden tiles enter as their 32-byte leaf hash, **never re-hashed**; split at the largest power of two `< n` |
| `canonical` | canonical JSON serialiser + strict parser | see 2.1 and 7 |
| `manifest` | manifest bytes, ML-DSA-44 verify | context `"VELUM/manifest/v1"` |
| `sidecar` | strict parser for the sidecar (embedded zTXt, or `NAME.velum.json` as fallback) | schema 2.1 |
| `xrpl` | read-only ledger client | see 3.3 |
| `recipe` | crop, rotate, downscale, brightness/contrast | integer only, see 3.2 |
| `level` | make a more redacted level from a level (editor) | drops salts of newly hidden tiles |
| `verify` | V1–V6 (section 4), returns a structured report | runs **all** checks, never throws |

Dependencies (permissive licences only, pin exact versions):

- `@noble/post-quantum` (MIT): `ml_dsa44.verify(sig, msg, publicKey, { context })`. Note the argument
  order: signature first. Unknown option keys throw, so a typo in `context` cannot silently disable it.
- `@noble/hashes` (MIT) for SHA-256, or WebCrypto `crypto.subtle.digest("SHA-256", …)`. (HMAC is only
  needed by the authority, which is CLI-only.)
- Inflate: `DecompressionStream("deflate")` (built in) or `fflate` (MIT).
- No XRPL SDK required: the client needs two read-only commands (3.3).

### 3.1 PNG: never read pixels from a canvas

Browsers may change pixels read back from `<canvas>`: colour management (`gAMA`, `iCCP`, `sRGB`
chunks), premultiplied alpha, and **anti-fingerprinting noise** (Firefox `resistFingerprinting`,
Brave, Safari). A verifier that reads pixels via `getImageData` can reject genuine images or accept
tampered ones.

- **Verification MUST decode PNG bytes in JS**: parse chunks, check CRCs, inflate `IDAT`, undo filters
  0–4 (None, Sub, Up, Average, Paeth).
- Accept only: bit depth 8, colour type 2 (RGB) or 6 (RGBA with every alpha = 255), no interlace,
  `IHDR` first, consecutive `IDAT` chunks, nothing after `IEND`, unknown critical chunks rejected,
  `W, H ≤ 16384` and `W · H ≤ 2^25` **checked on the header before inflating**, and the inflated data
  exactly `H · (1 + W · bpp)` bytes (never inflate more: zip-bomb guard).
- **Ancillary chunks: allow-list.** Accept only `tEXt`, `zTXt`, `iTXt`, `tIME` in evidence and
  rendition files. Anything else (`acTL`/`fcTL`/`fdAT` APNG frames, `tRNS`, `gAMA`, `cHRM`, `iCCP`,
  `sRGB`, `sBIT`, `eXIf`, …) can make a browser show other pixels than the verified ones: a failed
  check. Even so, display pixels you decoded and re-encoded yourself, not the original file.
- Apply a verifier pixel budget on the header (reference: `2^23` pixels) so a tiny file cannot cost
  minutes of CPU. Above the budget the result is COULD NOT VERIFY (not REJECTED: the image may well be
  authentic). Anything else: a failed check with a clear reason.
- `<img>`/`<canvas>` are fine for **display** only.
- Writing (editor): uncompressed PNG like the CLI: chunks `IHDR`, one `zTXt` `velum.sidecar` with the
  sidecar (keyword, `0x00`, compression method `0x00`, zlib data), `IDAT`, `IEND`; zlib header `78 01`,
  deflate *stored* blocks (≤ 65 535 bytes each), Adler-32, filter type 0 on every row. Never write
  any other metadata chunk.
- Reading the embedded sidecar: find the `zTXt` whose keyword is `velum.sidecar`, check method 0,
  inflate **at most 4 MiB** (refuse more), require ASCII. Two such chunks: error.
- Text chunks added by others (`tEXt`, `zTXt`, `iTXt`, `tIME`) do not change pixels, so the file still
  verifies; they are **not covered by the signature**. Do not display them as verified data.

### 3.2 Integer arithmetic must match Python exactly

- Every pixel operation uses integers. JS `number` is exact up to 2^53: fine for these sizes, but
  never use `/` without flooring.
- Python's `//` floors toward −∞; `Math.trunc` does not. Use a dedicated `floorDiv(a, b)` on integers.
- The recipe (`VELUM.md` §6.4) is the contract: order crop → rotate → resize → tone; resize by exact area
  weights with **one** half-up rounding at the end, `(sum + D // 2) // D` with `D = w_in · h_in`;
  tone `clamp(0, 255, ((v − 128)·(256 + contrast) + 128·256 + brightness·256 + 128) // 256)`. The
  recipe vectors confirm every case.

### 3.3 Reading the XRP Ledger from the browser

- Transport: WebSocket JSON to **several** public nodes, run by different operators where possible.
  Testnet: `wss://s.altnet.rippletest.net:51233`; the reference CLI uses the JSON-RPC nodes
  `https://s.altnet.rippletest.net:51234/`, `https://clio.altnet.rippletest.net:51234/` (full
  history) and `https://testnet.xrpl-labs.com/` (recent history only). Count each normalized host and port once toward the configurable quorum (default 2).
  Follow `VELUM.md` §7 ("Who the verifier trusts"), i.e. request `"binary": true`, recompute the
  transaction hash from `tx_blob`, check that `TxnSignature` verifies with `SigningPubKey` and that the
  key derives to `Account`, recompute the ledger hash from the `ledger` header and take the close
  time from it, and require the quorum to agree; disagreement is COULD NOT VERIFY.
- Always send `"api_version": 2`.
- Commands:
  - `{"command": "tx", "transaction": <hash>}` → use `validated`, `meta.TransactionResult`,
    `tx_json.Account`, `tx_json.TransactionType`, `tx_json.Memos`, `ledger_index`, and the close time.
    **Confirmed on a real Testnet response:** `close_time_iso` (e.g. `"2026-11-20T17:54:32Z"`) and
    `tx_json.date` (Ripple-epoch seconds; + 946 684 800 = Unix seconds) are both present; the reference
    used `tx_json.date`; it now takes `close_time` from the
    verified ledger header (above). A real response is in the Python repo at `tests/fixtures/tx_accountset_testnet.json`.
- "Anchored" means: `validated: true`, `tesSUCCESS`, `AccountSet`, sent by the expected account,
  **exactly one** memo, `MemoType` = hex of the ASCII type, `MemoData` = the expected bytes. Memo fields
  are hex; compare case-insensitively.
  - Manifest: type `velum/manifest` (`76656c756d2f6d616e6966657374`), data
    `SHA256(canonical(manifest)) ‖ SHA256(manifest_sig)`, 64 bytes, sent by `manifest.authority`.
  - Level: type `velum/level` (`76656c756d2f6c6576656c`), data `SHA256(canonical(level))`, 32 bytes,
    sent by `level.producer`.
- A transaction that does not exist (`error: txnNotFound`) is a failed check only when a quorum of
  full-history nodes (`server_info.complete_ledgers` one range from a low ledger) say so; from a node
  with recent history only it is COULD NOT VERIFY. A network failure, any
  other node error, or a transaction that is **not validated yet** is **not**: it is COULD NOT VERIFY
  (section 4), because the copy may become verifiable a few seconds later.
- Read the network from the node: `{"command": "server_info"}` → `info.network_id` (0 mainnet,
  1 testnet, 2 devnet). A node on another network abstains. Continue with the other nodes and require the configured quorum.

### 3.4 Trust list (who counts as an authority)

```json
[{ "name": "Example Forensic Unit", "network": "testnet",
   "xrpl_address": "r…", "mldsa44_pk_sha256": "<64 lowercase hex>",
   "not_after": "2027-12-31T23:59:59Z" }]
```

- Same format as `VELUM.md` §2. An entry matches when **both** `xrpl_address = manifest.authority`
  and `mldsa44_pk_sha256 = SHA256(authority_pk)`, and its `network` is the network of the node you query.
- `not_after` (or `null`) handles revocation and key rotation: accept a manifest only if its ledger
  signing time `t_A` is earlier.
- Shipped **inside** the Viewer/widget build (`trust-list.json`), versioned with releases.
- **Never** taken from the embedding page, URL parameters or the sidecar. If a page could supply the
  pin, any page could vouch for a fake authority.
- Display the authority **name from the trust list**, never a name from the sidecar.

## 4. The verifier (`VELUM.md` §7)

All six checks run and are reported, even after a failure. **Sidecar source:** the one embedded in the
evidence PNG wins; an external `NAME.velum.json` is used only when the PNG carries none; report which
one was used (`sidecar` fact). If there is none, or it does not parse, V1 fails with the reason and
V2–V6 are reported as "not run".

| Check | Passes when |
|---|---|
| **V1 authority signature** | a trust-list entry matches (3.4) and `ML-DSA-44.Verify(authority_pk, canonical(manifest), manifest_sig, ctx "VELUM/manifest/v1")` |
| **V2 authority anchor** | `manifest_tx` anchors the manifest (3.3); its close time `t_A` is before the entry's `not_after` |
| **V3 pixels** | the evidence decodes to `W × H`; every real pixel of every hidden tile is (0,0,0); visible leaves (salt + pixels + synthesised padding) and hidden leaf hashes rebuild `manifest.root` |
| **V4 level anchor** | `level.manifest_tx = manifest_tx`; `level_tx` anchors the level, sent by `level.producer`; its ledger index ≥ that of `manifest_tx` |
| **V5 redaction rules** | tiles outside `level.crop` are hidden; crop and recipe can be applied (resize only shrinks); the sidecar's `hidden` list equals the bitmap |
| **V6 rendition** | if a rendition is given, the recipe applied to the evidence gives exactly its pixels; otherwise passes as "no rendition given" |

**Outcome** (show these words to users):

| Reference result | UI | When |
|---|---|---|
| `ACCEPT` | **VERIFIED** | every check passed |
| `REJECT` | **REJECTED** | at least one check failed for a reason other than the network |
| `UNVERIFIABLE` | **COULD NOT VERIFY** | every failure is inconclusive: "could not reach the ledger" (offer retry) or "above this verifier's pixel budget" |

**Fail closed:** any unexpected error inside a check (a bug, a library exception) makes that check fail
with "internal error"; it never crashes the page and never counts as a pass.

**Facts on VERIFIED:** authority name (trust list), signing time `t_A`, the producer account and the
level's anchor time (`published_by`, `published_at`), the hidden percentage (hidden real pixels / all
pixels, one decimal), and the tile mask (`rows` strings of `cols` characters, `#` hidden, `.` visible).

## 5. A — Viewer

### Input

- Drag and drop: `NAME.png` alone is enough (it carries the sidecar); `NAME.velum.json` only if the PNG
  lost its metadata; optional `NAME.public.png` to check the rendition.
- Or URL: `/?evidence=<url>[&sidecar=<url>][&rendition=<url>]` (the sidecar only if the PNG lost it). Remote files need CORS from their host;
  if a fetch fails, explain CORS and offer drag and drop.

### Flow

1. Parse the sidecar; show "Verifying…" with per-check progress (V1…V6).
2. Run `verify` in a **Web Worker** (720p: ~2.7 MB evidence, 240 tiles; the Python reference takes
   ~1.5 s including a rendition; target < 2 s after download).
3. Show the result.

### Result screen

- Big status: **VERIFIED**, **REJECTED** (list every failed check with its reason), or
  **COULD NOT VERIFY** (retry button).
- The image: the rendition if present, else the evidence. Toggle: **redaction mask overlay** (hidden
  tiles outlined).
- Facts (section 4): authority, signing time, image size, % hidden.
- **Published by**: the producer account and time, with Explorer links for the level anchor and the
  manifest anchor (`https://testnet.xrpl.org/transactions/<hash>`).
- Downloads: the three files, and a JSON report.

### Must not

- Show VERIFIED before every check has passed.
- Reuse a previous result for a different set of files.
- Show metadata found in the PNGs as if it were verified.

## 6. B — Editor (producer role)

### Flow

1. **Open** a level (evidence + sidecar). Verify it first with the same `verify`; refuse to edit a
   level that does not verify.
2. **Connect the wallet** and read its address: it becomes `level.producer`, and the same account must
   sign the anchor (V4 checks it).
3. **Redact**: tile grid overlay (64 px). Click or drag to hide tiles. Tiles already hidden in the
   source level are locked (shown, not toggleable): redaction is one-way.
4. **Crop** in whole tiles; tiles outside the crop are hidden automatically (`VELUM.md` §6.3.2).
5. **Recipe**: rotate (0/90/180/270), downscale to a target size (no upscaling; offer "keep aspect"),
   brightness and contrast sliders in `[−255, 255]`.
6. **Preview** the rendition live (computed with `velum-js`, the same code the verifier runs).
7. **Build the new level** exactly like the reference (`level.py`):
   `hidden = source hidden ∪ newly hidden ∪ outside the crop`; for each newly hidden tile compute its
   leaf hash from its salt and pixels, **delete its salt**, paint its real pixels black.
   Descriptor: `{v: 1, manifest_tx: source.manifest_tx, producer, hidden, crop, recipe}`.
8. **Anchor**: build an `AccountSet` with one memo (`MemoType` = `76656c756d2f6c6576656c`,
   `MemoData` = `SHA256(canonical(descriptor))` in hex) and ask a **wallet extension** (GemWallet,
   Crossmark or Xaman; pick one first) to sign and submit it. When validated, write `level` and
   `level_tx` into the new sidecar (manifest fields copied from the source). Never ask for, accept or
   store a seed.
9. **Export** evidence PNG, sidecar, rendition PNG; re-run `verify` on the exported files before
   declaring success.

### Must not

- Ship the salt of any hidden tile, or leave original pixels under a black tile.
- Derive a level from a rendition (`*.public.png`); only from evidence + sidecar.
- Offer authority signing. That is CLI-only.

## 7. C — Embed widget

### Markup for publishers

```html
<script src="https://<viewer-origin>/embed/v1/velum-embed.js"
        integrity="sha384-…" crossorigin="anonymous" defer></script>

<img src="photo.public.png" alt="…"
     data-velum-evidence="photo.png">
<!-- optional, only if the evidence PNG lost its metadata: data-velum-sidecar="photo.velum.json" -->
```

### Behaviour

- On load: find `img[data-velum-evidence]`, add a small badge ("VELUM · Verify") in a Shadow DOM.
  Load nothing heavy yet.
- On click: lazy-load the verifier (ML-DSA code included), fetch the evidence (and the sidecar file only if the evidence has none), **fetch the bytes
  of the image's `src`** (never read them back from the page, see 3.1) and verify them **as the
  rendition** (or as the evidence if it is the evidence itself). Show a popover: authority name,
  signing date, % redacted, published by / when, and **"Full report ↗"**, a link that opens the Viewer
  on its own origin with the same URLs.
- Small: aim for < 15 KB gzipped before click; the verifier chunk loads on demand.

### Security model (put this in the publisher docs)

- The embedding page controls its own DOM: a hostile page can draw a fake "verified" badge. The inline
  popover is a **convenience**; the **Viewer on the VELUM origin is the authoritative result**.
- The widget reads only URLs from the page, never pins or authority names (3.4).
- Publishers need CORS on the sidecar and evidence (`Access-Control-Allow-Origin`) and a CSP that
  allows the widget origin (`script-src`) and the XRPL WebSocket (`connect-src`).

## 8. Testing and acceptance

**Conformance vectors**, available now in the Python repo. `velum-js` must reproduce every value byte
for byte; CI runs them.

- `tests/vectors/core_v1.json`
  - `png_decode`: PNGs with every filter, compressed and stored, opaque RGBA, ancillary chunks →
    expected size and `SHA256(rgb)`;
  - `png_reject`: transparency, 16-bit, palette, interlace, bad CRC, data after IEND, truncated,
    non-consecutive IDAT, too many pixels;
  - `png_verify_reject`: PNGs that decode but that a verifier must refuse (APNG `acTL`, `tRNS`, `gAMA`,
    `sRGB`, `iCCP`, `eXIf`, `PLTE`);
  - `png_sidecar`: a PNG with an embedded `velum.sidecar` (expected text), one without (null), and one
    with two such chunks (`"ERROR"`);
  - `tree`: salts, leaves, roots for n = 1, 2, 3; `image_case`: a 70×66 image (edge tiles) with tile
    hashes, leaves, root; `canonical_json`: values and their canonical text.
- `tests/vectors/levels_v1.json`
  - `ledger`: a **dump of the test ledger**, `{tx_hash: {validated, result, tx_type, account, memos:
    [[type as text, data hex]], ledger_index, close_time (Unix seconds)}}`. Use it as a fake XRPL
    client. Note: memo types here are **decoded text**; a live node returns them hex-encoded.
  - `trust_lists`: `default`, `empty`, `revoked`.
  - `cases`: each with `evidence_png`, `sidecar` (null when only the embedded one exists), `rendition_png` (or null), `trust`, `expected_status`
    (`ACCEPT`/`REJECT`) and `expected_failed` (the exact list of failing checks). PNGs are referenced by
    SHA-256; their base64 bytes are in `png_files`. Cases: the three honest copies (authority, lab,
    newsroom with rendition), flipped pixel, hidden tile not black, tampered rendition, untrusted
    authority, revoked authority, level anchored by another account, level paired with another level's
    anchor, APNG frame added, `tRNS` on black, two embedded sidecars (never a fallback), float in the
    sidecar JSON.
  - `recipe`: rotations, fractional-weight resize, tone, and the newsroom's crop + recipe;
    `bitmap`: encodings.
- **Strict JSON numbers:** `JSON.parse` cannot tell `1.0` from `1`. Scan the raw number tokens
  (`-?[0-9]+` only) before parsing, or use a parser that keeps them. The float case above must REJECT.
- **Live samples**: `make demo` (backend step 3) writes the AUTHORITY → LAB → NEWSROOM copies of the
  pizza case to `out/demo/` (verifiable on Testnet) plus two attack files; ask for a copy.
- **Browsers:** latest Chrome, Firefox (with `resistFingerprinting` on), Safari.
- **Acceptance:** every vector case gives its expected status and failing checks; network off gives
  COULD NOT VERIFY; results identical to `velum verify` on the same files.

## 9. Milestones (aligned with the backend build plan)

| Milestone | Needs | Content |
|---|---|---|
| F1 | **available now** (backend step 1) | `velum-js` core + `verify` passing every vector, using the ledger dump as fake client |
| F2 | **available now** (backend step 2) | live XRPL client; Viewer with drag and drop |
| F3 | backend step 3 (demo copies) | Viewer complete (mask, published by); embed widget |
| F4 | wallet choice | Editor with export and wallet anchoring |

## 10. Out of scope

Authority signing and key management, chain of custody (v1 records only who published each copy),
lossy formats (JPEG/WebP), metadata, mobile apps, any server that stores images or keys, Devnet-only
features (`Sponsor`: see `VELUM.md` §10).

## 11. Open questions for the frontend developer

1. Framework for A/B (vanilla TS, React, Svelte…): your choice; the widget stays vanilla.
2. Hosting origin for the Viewer and widget (needed for the trust model and SRI).
3. Which wallet extension first (GemWallet, Crossmark, Xaman).
4. Who maintains the trust list and how a new authority gets added.

## Changelog

- **v0.6**: implemented in `web/` (Nuxt 3). One sidecar, one level (no chain); strict JSON parser;
  embedded sidecar read and written by the Editor; PNG strict mode, 2^25 cap, 2^23 verifier budget
  (above it COULD NOT VERIFY); trust entry must match the ledger's network; ledger reads need 2 of 3
  nodes, each answer checked (`tx_blob` hash, master-key signature, ledger header hash), with
  `ripple-binary-codec` and `ripple-keypairs`; vectors read from `tests/vectors`; samples are the real
  `make demo` files, verified live (no recorded ledger in the app).

- **v0.5**: the sidecar travels inside the evidence PNG (`zTXt` `velum.sidecar`); external file only
  as a fallback; widget needs only `data-velum-evidence`; new vectors (`png_sidecar`, embedded case).
- **v0.4** (backend step 2 done): `tx` response fields confirmed on Testnet (real fixture in the repo);
  `txnNotFound` vs other node errors; not-yet-validated transactions are COULD NOT VERIFY; the network
  comes from `server_info.network_id`; the backend now also matches the trust-list `network`.
- **v0.3** (backend step 1 done): formats frozen at version 1; one anchored level per copy (`level` +
  `level_tx`, no chain of custody); PNG limits (2^25 pixels checked on the header, consecutive IDAT);
  verifier outcomes, facts and fail-closed rule; full vector description; editor must use the wallet
  address as `producer`; trust-list `network` must match the node.
- **v0.2**: review fixes to the design (RFC 6962 wording, sidecar schema, resize rounding, `not_after`).
- **v0.1**: first draft.
