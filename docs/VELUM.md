# VELUM: verifiable redaction of signed images, anchored on the XRP Ledger

Status: the Python reference implements steps 1–3, including the CLI and XRPL Testnet anchors.
This document is the contract between the Python reference and any
other implementation (the browser library in [`frontend-spec.md`](frontend-spec.md)).

## 1. What VELUM does

A highly trusted **authority** (a police forensic unit, a court, an agency) takes a photo and signs it
once. Then the photo travels to recipients (forensic lab, analysts, newsrooms, the public), and
anyone holding a copy may **black out more of it** before passing it on. Every copy, at every level of
redaction, can be checked by anyone:

- the visible pixels are exactly the pixels the authority signed;
- the black areas hide pixels the authority signed, and reveal nothing about them;
- the copy was published on the XRP Ledger, by a known account, at a known time.

Each copy records **who published it and when**, not the whole history of who redacted what before
(see §8.3; a full chain of custody is future work).

Nobody re-signs anything. One signature from the authority covers every redacted copy ever made.

```
AUTHORITY ── signs the tile Merkle root (ML-DSA-44) ── anchors the manifest on XRPL
    │
    L0  full image, anchored by the authority ─────────▶ forensic experts
    │
   LAB ── blacks out licence plates ── anchors its copy ─▶ analysts
    │
NEWSROOM ── blacks out faces, crops, shrinks ── anchors its copy ─▶ the public (PNG)
    │
ANYONE ── velum verify ── ACCEPT / REJECT, with the redaction mask
```

Non-goals: no frontend in this repository (command line only; a separate browser Viewer, Editor and
embed widget are specified in [`frontend-spec.md`](frontend-spec.md)), no lossy formats, no metadata
(EXIF is ignored), no zero-knowledge proofs.

## 2. Actors, keys and trust

| Actor | Keys | Does |
|---|---|---|
| **Authority** | ML-DSA-44 key (the signing key, post-quantum) + an XRPL account | Signs the manifest, anchors it, publishes L0. Keeps the **master** (original image + salt secret `K`) |
| **Producer** (LAB, NEWSROOM, anyone downstream) | an XRPL account only | Derives a more redacted level from the level it received, anchors it |
| **Verifier** (anyone) | none; holds a **trust list** | Runs `velum verify` against the public ledger |

**Trust list.** The verifier knows each authority it trusts from a list obtained out of band (like the
root certificates shipped with a browser), never from the files being verified:

```json
[{ "name": "Example Forensic Unit", "network": "testnet",
   "xrpl_address": "r…", "mldsa44_pk_sha256": "<64 lowercase hex>",
   "not_after": "2027-12-31T23:59:59Z" }]
```

- `mldsa44_pk_sha256` is what keeps the scheme post-quantum: anything stored on the ledger (a DID, a
  memo) can be rewritten or forged with the authority's *classical* XRPL key, which a quantum attacker
  could recover from its public key.
- `not_after` (or `null`) handles **revocation and key rotation**: a manifest is accepted only if its
  signing time `t_A`, read from the ledger, is earlier than `not_after`. Rotating a key means adding a
  new entry with the new key and setting `not_after` on the old one: images signed before stay valid,
  because their anchors are in immutable ledger history.

## 3. Image model

- **Pixels:** 8-bit RGB, row-major, `W × H`, `1 ≤ W, H ≤ 16384` and `W · H ≤ 2^25` (33.5 MP, enough for 8K).
  The limit is checked on the PNG header, before anything is inflated: a small file must not be able to
  make a verifier inflate and process gigabytes.
- **Reading PNG** (any implementation): any valid PNG with bit depth 8, colour type 2 (RGB) or 6 (RGBA
  with every alpha = 255), no interlace, any compression level and any row filters (0–4). CRCs are
  checked; `IDAT` chunks must be consecutive (as libpng and browsers require); ancillary chunks are
  ignored for decoding. Anything else is rejected.
- **What a viewer shows must be what was verified.** Some ancillary chunks change the displayed image
  without touching `IDAT`: APNG frames (`acTL`, `fcTL`, `fdAT`), `tRNS` (makes a colour, e.g. black,
  transparent), colour management (`gAMA`, `cHRM`, `iCCP`, `sRGB`, `sBIT`) and `eXIf` (orientation).
  The verifier (V3 for the evidence, V6 for the rendition) therefore accepts only an **allow-list** of
  ancillary chunks that no viewer renders as pixels: `tEXt`, `zTXt`, `iTXt`, `tIME`. Any other
  ancillary chunk is a failure. (Reading an *original* for signing stays lenient: the authority's
  evidence is rewritten without those chunks.)
- **Verifier budget:** pure-language PNG decoding and recipes cost CPU per pixel, and a tiny file
  (Paeth-filtered zeros) can declare millions of pixels. A verifier may refuse, on the header and before
  inflating, images above a local pixel budget. The reference uses `2^23` pixels (8.4 MP, 4K UHD),
  configurable with `VELUM_MAX_VERIFY_PIXELS`. This is verifier policy, not a format limit, so an image
  above the budget is **UNVERIFIABLE** (inconclusive), never REJECT: it says nothing about authenticity.
  The reference signer refuses images above the default budget, so that what it signs, default
  verifiers can check.
- **Writing PNG** (reference writer): uncompressed. Chunks `IHDR`, optionally one `zTXt` with keyword
  `velum.sidecar` (§6), one or more `IDAT`, `IEND` only; zlib header `78 01`, deflate *stored* blocks,
  Adler-32; filter type 0 on every row.
- Verification compares **decoded pixels**, never file bytes: two PNGs with different bytes and the
  same pixels are the same image.
- **Tiles:** a fixed `T = 64` pixel grid. `cols = ceil(W / 64)`, `rows = ceil(H / 64)`,
  `n = cols · rows`, tile index `i = row · cols + col`. For 1280 × 720: 20 × 12 = 240 tiles.
- **Edge tiles** are virtually padded with zeros to 64 × 64 (720 = 11 · 64 + 16, so the last row has
  16 real pixel rows and 48 padding rows). Padding is **never stored or transmitted**: whoever hashes a
  tile synthesises it. See §8.1.

## 4. Commitment (authority, once per image)

Notation: `‖` is byte concatenation; `u32be(i)` is `i` as 4 bytes big-endian; strings are ASCII bytes
without terminator; hex is lowercase unless stated.

```
K        = 32 random bytes                                    per-image salt secret, part of the master
salt_i   = HMAC-SHA256(key = K, msg = "VELUM/salt/v1" ‖ u32be(i))                         32 bytes
tile_i   = the 64 × 64 block of tile i, rows top to bottom, pixels left to right, R G B;
           pixels outside W × H are (0, 0, 0)                                          12 288 bytes
d_i      = "VELUM/leaf/v1" ‖ u32be(i) ‖ salt_i ‖ tile_i                                12 337 bytes
leaf_i   = SHA256(0x00 ‖ d_i)                                    the RFC 6962 leaf hash of entry d_i
root     = MTH(d_0, …, d_{n-1})                                  RFC 6962 §2.1 Merkle Tree Hash
```

`MTH` exactly as in RFC 6962 §2.1, written in terms of the leaf hashes (which is how hidden tiles enter
it, since only `leaf_i` is known for them):

```
MTH of one entry       = leaf_0                                   (= SHA256(0x00 ‖ d_0))
MTH of n > 1 entries   = SHA256(0x01 ‖ MTH(first k) ‖ MTH(remaining n − k)),
                         k = largest power of two strictly smaller than n
```

**Never hash a leaf hash again.** A hidden tile contributes the 32-byte `leaf_i` from the sidecar
as-is; a visible tile contributes `SHA256(0x00 ‖ d_i)` computed from its salt and pixels. There are no
padding leaves, so the tile count cannot be reinterpreted.

**Test vectors** (computed with Python's `hashlib` and `hmac`): `K = 00 01 02 … 1f` (bytes 0 to 31),
every `tile_i` all zeros.

```
salt_0 = d760c2b4790d8555c845941f0a37046f92b78ee35ef0dab13e749bb843a0573c
salt_1 = 9e195931165f4b0f08aa359f48f48d1a1b283f9d739a2a27fd7dd421bcf61165
salt_2 = 9d98a6bfad1c1f6480b535ed2296fff2acde65c5e43af5736e54d6cdd9315f87
leaf_0 = 3978b5fa612f7d0d0073d57b4a6b463ea1bb9fd38174bd188274c54cae30fabc
leaf_1 = 685976bfcc3aec539e5def6995b36f4dc275de24ab05b896dc2479395d9a8354
leaf_2 = 4b91a7878c424b0cf5905647103c3b7811ce305af90036cfb07726cf7efafd7b
root (n = 1, tile 0)       = 3978b5fa612f7d0d0073d57b4a6b463ea1bb9fd38174bd188274c54cae30fabc
root (n = 2, tiles 0–1)    = c9a0d01fd7d235261c8e223cb106f86843b9713a7f0c36b75ef294ab6af06de1
root (n = 3, tiles 0–2)    = 9fd03a9407f4c01d5e024a957d979b7227b913511622313e7ad73fa41b4266ca
```

Why salts: without `salt_i`, `leaf_i` says nothing about the pixels, even when the tile is almost
entirely black or padding, and even to a quantum attacker (256-bit preimage; Grover leaves 128 bits).
Salts are derived from one secret `K` so the master is a single 32-byte value plus the original image.
Revealing `salt_i` for a visible tile reveals nothing about `K` or other salts (HMAC is a PRF).

## 5. Manifest and authority anchor

**Canonical JSON** (used for the manifest and the level descriptors): an object whose values are only
strings of printable ASCII (0x20–0x7E) without `"` or `\`, integers (negative only where a field allows
it), `null`, arrays and nested objects of the same; no floats, no booleans. With these limits no
encoder ever needs an escape sequence, so every language writes the same bytes. Serialised with keys sorted by byte value, no whitespace (`,` and `:` separators), ASCII only.
In Python: `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)`. Hashes and
signatures are hex lowercase; XRPL transaction hashes are hex **uppercase** (as XRPL prints them).

```
manifest = { "v": 1, "w": W, "h": H, "tile": 64, "root": hex(root),
             "authority": "<authority XRPL address>", "pq_alg": "ML-DSA-44" }
sig      = ML-DSA-44.Sign(sk_A, canonical(manifest), ctx = "VELUM/manifest/v1")       2420 bytes
```

Anchor, sent by the **authority's XRPL account**: an `AccountSet` with exactly one memo

```
MemoType = hex("velum/manifest")
MemoData = SHA256(canonical(manifest)) ‖ SHA256(sig)            64 bytes
```

The close time of the validated ledger that contains it is the **signing time** `t_A`. `AccountSet`
with no fields set changes nothing and locks no reserve: it is a pure, cheap anchor.

## 6. Levels

A **level** is one redacted copy, in three files:

| File | Content |
|---|---|
| `NAME.png` | **Evidence image**: the full `W × H` frame, every hidden tile painted black (0,0,0); it also carries the sidecar in a `zTXt` chunk `velum.sidecar` (zlib-compressed ASCII JSON, at most 4 MiB inflated), so this one file is enough to verify the level |
| `NAME.velum.json` | **Sidecar** (§6.2) as a separate file, for channels that strip PNG metadata; used only when the PNG carries none |
| `NAME.public.png` | **Rendition** (optional): the evidence image after the level's public recipe, the image you publish |

### 6.1 Level descriptor (what the producer of a copy anchors)

```
descriptor = {
  "v": 1,
  "manifest_tx": "<UPPERCASE hash of the authority anchor>",
  "producer":    "<XRPL address that anchors this descriptor>",
  "hidden":      "<hex bitmap>",
  "crop":        [col0, row0, cols, rows] | null,                          tile units
  "recipe":      { "rotate": 0|90|180|270, "resize": [w, h] | null,
                   "brightness": int, "contrast": int } | null
}
```

- **`hidden` bitmap:** `ceil(n / 8)` bytes, **MSB first**: tile `i` is bit `7 − (i mod 8)` of byte
  `i div 8`; 1 = hidden. Unused trailing bits are 0. Example, n = 10 with tiles 0 and 9 hidden:
  `80 40` → `"8040"`.
- **Signed integers** in `recipe` (brightness, contrast in `[−255, 255]`) are the only negative numbers
  allowed in canonical JSON. `recipe: null` means identity.

Anchor, sent by **the `producer` account**: `AccountSet` with exactly one memo,
`MemoType = hex("velum/level")`, `MemoData = SHA256(canonical(descriptor))` (32 bytes). A copy made
from the original is produced and anchored by the authority itself.

### 6.2 Sidecar schema

```json
{
  "velum": 1,
  "manifest": { "authority": "r…", "h": 720, "pq_alg": "ML-DSA-44", "root": "…", "tile": 64, "v": 1, "w": 1280 },
  "manifest_sig": "<hex, 2420 bytes>",
  "authority_pk": "<hex, 1312 bytes>",
  "manifest_tx": "<UPPERCASE hash>",
  "level": { …the descriptor of this copy… },
  "level_tx": "<UPPERCASE hash of its anchor>",
  "visible": [[0, "<salt_0 hex>"], [1, "<salt_1 hex>"], …],
  "hidden":  [[37, "<leaf_37 hex>"], [38, "<leaf_38 hex>"], …]
}
```

- `visible` and `hidden` are sorted by tile index; every index `0 … n−1` appears **exactly once** across
  the two lists, and `hidden` lists exactly the tiles set in the level's bitmap.
- **Strict parsing:** unknown, missing or duplicate keys, wrong lengths, uppercase hex where lowercase
  is required, any number not written as an integer (`1.0`, `1e3`: JavaScript's `JSON.parse` cannot
  tell them from `1`, so implementations must check the raw token against `-?[0-9]+`), booleans, or a
  salt next to a hidden tile make the sidecar invalid. A hidden tile's salt must never travel: with it, a tile of predictable content could
  be guessed.

### 6.3 Rules a level must obey

1. **Black can only be added.** Anyone holding a level can make a more redacted one (replace a visible
   tile by its leaf hash and drop its salt). Nobody can make a less redacted one without the authority's
   master: a hidden tile's salt is not in the sidecar, so it cannot be shown again. This is a property of
   the data, not a rule the verifier has to check.
2. **Crop is tile-aligned and hides:** every tile outside the crop rectangle must be hidden. A crop can
   never keep pixels in the evidence that the public image does not show.
3. **Derive from evidence, never from a rendition.** A new level is made from another level's evidence
   image and sidecar. A rendition is only for publishing.

### 6.4 Rendition recipe (public, deterministic, integers only)

Applied in this order to the evidence image. `//` is **floor division** (rounds toward −∞, as in
Python); never use rounding functions such as Python's `round()` (banker's rounding).

1. **Crop** (if `crop` is not null): pixel rectangle `x0 = col0·64`, `y0 = row0·64`,
   `w = min(cols·64, W − x0)`, `h = min(rows·64, H − y0)`. Requires `cols, rows ≥ 1` and the rectangle
   inside the tile grid.
2. **Rotate** clockwise, input `w × h`, output pixel `(r, c)`:
   - 90: output `h × w`, `out[r][c] = in[h−1−c][r]`
   - 180: output `w × h`, `out[r][c] = in[h−1−r][w−1−c]`
   - 270: output `h × w`, `out[r][c] = in[c][w−1−r]`
3. **Resize** (if not null) from `w_in × h_in` down to `w_out × h_out`, `1 ≤ w_out ≤ w_in`,
   `1 ≤ h_out ≤ h_in`, by exact area averaging. On a common integer scale, source column `x` covers
   `[x·w_out, (x+1)·w_out)` and output column `X` covers `[X·w_in, (X+1)·w_in)`:
   ```
   wx(X, x) = max(0, min((x+1)·w_out, (X+1)·w_in) − max(x·w_out, X·w_in))     Σ_x wx = w_in
   wy(Y, y) = same with heights                                               Σ_y wy = h_in
   out[Y][X] = ( Σ_y Σ_x wy(Y,y) · wx(X,x) · in[y][x] + D // 2 ) // D,       D = w_in · h_in
   ```
   per channel; one rounding (half up) at the very end.
4. **Brightness / contrast**, per channel, `contrast, brightness ∈ [−255, 255]`:
   `out = clamp(0, 255, ((in − 128)·(256 + contrast) + 128·256 + brightness·256 + 128) // 256)`.
   `0 / 0` is the identity.

## 7. Verification

Input: `NAME.png`, optionally `NAME.velum.json` and `NAME.public.png`; the trust list; an XRPL node.
The sidecar embedded in the PNG wins; the external file is used only when the PNG carries no
`velum.sidecar` chunk (or is not a readable PNG at all, which V3 then reports). A broken embedded
sidecar (two `velum.sidecar` chunks, unknown compression, non-ASCII, over 4 MiB) is a V1 failure and
never falls back to the external file. If both exist and differ, the report says so. Its origin does
not make it trusted: it goes through every check.
**All checks run**; the result lists every failure. Any unexpected error inside a check is a failure
(fail closed), never a crash and never a pass. A network error is reported as "could not verify",
never as ACCEPT; a transaction that exists but is **not validated yet** is reported the same way (retry),
and the verifier reads the network from the node (`server_info.network_id`), not only from its
configuration.

**Who the verifier trusts for ledger facts.** One node could otherwise invent a whole transaction or
its time. The reference verifier asks every node in `XRPL_RPC_URLS` and, from each answer:
1. requests the transaction in binary and recomputes its hash, `SHA-512Half(0x54584E00 ‖ tx_blob)`;
   it must equal the requested hash, which binds account, type and memos to that hash;
2. checks that the body is signed by the master key of its own `Account` (`SigningPubKey` derives to
   `Account`, `TxnSignature` verifies). The hash alone is not enough, because a forger chooses the hash
   written in the sidecar: without the signature a node could serve a made-up body for any account.
   Accounts that sign with a regular key or multi-sign are not supported (the node abstains);
3. reads the result from the binary metadata and requires `validated: true`;
4. fetches the header of the ledger that holds it, recomputes the ledger hash
   (`SHA-512Half(0x4C575200 ‖ header fields)`), requires it to equal the transaction's `ledger_hash`,
   and takes the close time from that header.

Each RPC host and port gets one vote, including when several configured URLs point to it.
At least `XRPL_QUORUM` nodes (default 2) must answer, and every answering node must agree on ledger
index, ledger hash, close time and result; otherwise the result is "could not verify". A node that is
unreachable, reports another network or no `network_id`, or lacks the history, abstains. "Not found"
is a failure only when a quorum of **full-history** nodes say so (one `complete_ledgers` range starting
at or below `XRPL_HISTORY_FLOOR`, default 1000); a node with recent history only abstains, so a genuine
old anchor is never reported as forged. So one node cannot invent an anchor for an account whose key it does not
hold. Limits: inclusion of the transaction in the ledger's transaction tree and the UNL validations of
the header are not checked (§10), so a node could still place a genuine transaction in another real
ledger (an earlier close time), or answer "not found"; only the quorum stops that, and nodes that
collude can still lie. Choose nodes run by independent operators.

"Anchored" below always means: a **validated** transaction with result `tesSUCCESS`,
of type `AccountSet`, with **exactly one** memo of the stated type and data.

| Check | Condition |
|---|---|
| **V1 signature** | the sidecar parses strictly; a trust-list entry has `xrpl_address = manifest.authority` and `mldsa44_pk_sha256 = SHA256(authority_pk)`; `ML-DSA-44.Verify(authority_pk, canonical(manifest), manifest_sig, ctx = "VELUM/manifest/v1")` |
| **V2 authority anchor** | `manifest_tx` is anchored by `manifest.authority` with memo `velum/manifest` = `SHA256(canonical(manifest)) ‖ SHA256(manifest_sig)`; its close time `t_A` is earlier than the entry's `not_after` |
| **V3 pixels** | the evidence image is `W × H`; every real pixel of every hidden tile is (0,0,0); rebuilding the leaves (visible: salt + pixels + synthesised padding; hidden: given `leaf_i`) gives `MTH = manifest.root` |
| **V4 level anchor** | `level.manifest_tx = manifest_tx`; `level_tx` is anchored by `level.producer` with memo `velum/level` = `SHA256(canonical(level))`; its ledger index is ≥ that of `manifest_tx` |
| **V5 redaction rules** | tiles outside the level's `crop` are hidden; its crop and recipe can be applied (§6.4, resize only shrinks); the sidecar's `hidden` list equals the level's bitmap |
| **V6 rendition** | if a rendition is given: the last descriptor's recipe (§6.4) applied to the evidence image gives exactly its pixels |

Output on ACCEPT: the authority (name from the trust list, never from the files), `t_A`, the account
that published this copy and when, the percentage of the image hidden, and the tile mask.

## 8. Security analysis

### 8.1 Zero padding of edge tiles: safe, under four rules

| Risk if done carelessly | Rule that removes it |
|---|---|
| A producer declares a different height, turning padding into "real" black rows, or real rows into padding | `W` and `H` are inside the signed manifest |
| Padding bytes carried in a file become a covert channel or a second encoding of the same tile | Padding is never read from input; the hasher always synthesises zeros |
| A tile moved to another position still matches | `d_i` contains the index `i` |
| A tree with padding leaves lets someone claim a different tile count | RFC 6962 tree, no padding leaves, `n` derived from the signed `W`, `H` |

**Can a mostly-padding (or mostly-black) hidden tile be brute-forced?** No: its leaf contains the
256-bit secret `salt_i`, so guessing the pixels also means guessing the salt, whatever the pixels are.
Low-entropy content only becomes guessable if the salt is known (see 8.3, the master).
**Conclusion: zero padding introduces no weakness; no other padding scheme is needed.**

### 8.2 What VELUM guarantees

- **Authenticity** of every visible pixel, at every level, against a quantum adversary: ML-DSA-44
  (EUF-CMA) + SHA-256 collision resistance.
- **Hiding** of every black tile, forever: salted hashes, no discrete logarithms anywhere.
- **Ordering and time:** each level is tied to the XRPL account that anchored it and to a ledger time.

### 8.3 What it does not, and must be said

- **No chain of custody.** A copy says who published *it* and when, not who redacted what before it.
  Anyone may make and anchor a more redacted copy of any level they hold (redaction is permissionless
  and can only add black). Many copies of the same photo can coexist; none is "the latest".
- **Producers are accounts, not identities.** Nothing ties an XRPL account to "the lab". Binding
  accounts to organisations (e.g. XRPL Credentials) is future work.
- **The mask is public.** Everyone sees *where* and *how much* was blacked out, at 64-pixel precision.
- **Levels are linkable.** All copies share the root, so anyone can tell two copies come from the same
  photo, including a leaked, less redacted one.
- **A leaked level undoes the redactions of its descendants** on the tiles it shows.
- **Hiding depends entirely on the salts staying secret.** Whoever obtains `K` knows every salt and can
  guess hidden tiles of predictable content (uniform areas, known text), regardless of padding; with
  `K` and the original image, everything. In production `K` and the ML-DSA key live in an HSM.
- **Authentic is not truthful.** Heavy redaction can change what a photo means; the verifier always
  prints the mask and the hidden percentage.
- **Metadata is outside the signature.** VELUM writes PNGs with only `IHDR`, `IDAT`, `IEND` and its own
  `velum.sidecar` chunk (which is not trusted metadata: every byte of it is checked by V1–V6), so its
  evidence images and renditions carry no EXIF (`eXIf`), text, time or colour-profile chunks, whatever
  the original contained; only the authority's master keeps them. Chunks that change what is displayed
  are refused by the verifier (§3), but text chunks (`tEXt`, `zTXt`, `iTXt`) and `tIME` can still be
  added to a VELUM PNG and it still verifies. Such chunks are not authenticated and may carry anything,
  from a fake GPS position to the hidden content itself. Treat every metadata chunk in a VELUM file as
  unverified.
- **Ledger facts come from XRPL nodes.** The verifier trusts a quorum of the nodes it is configured
  with for each transaction's existence, result and time (§7); colluding nodes could backdate a
  signing time and defeat `not_after`. Configure nodes run by independent operators.
- **Testnet anchors do not last.** Testnet (and Devnet) are reset from time to time, which erases every
  anchor: a genuine Testnet level then reads "could not verify" (or "not found" on a full-history node
  of the new network). Production anchors belong on Mainnet.
- **`published_by` is "an account that anchored this descriptor", not "the first publisher".** Anyone
  can re-anchor a public level's descriptor under their own account and pair it with the same files.
- **The master must stay apart from what is shared.** The CLI writes each `K` to a private folder
  (`~/.velum/masters`, or `VELUM_MASTER_DIR`), never next to the level files, and never deletes one:
  replacing a master moves the old one aside.
- **EXIF orientation of the original is ignored.** A phone photo whose EXIF says "rotate 90°" is signed
  as stored, unrotated. The authority should rotate the pixels before signing if needed.
- **Classical parts:** XRPL account keys and consensus. A quantum attacker could anchor levels in a
  producer's name, but could not forge pixels, and past ledger history stays immutable (hash chain).
- **Size:** verification needs the evidence image (about 2.7 MB uncompressed at 720p), even when the
  rendition is small.
- **Prototype crypto:** `dilithium-py` is pure Python and not constant-time.

## 9. On-ledger footprint

Per image: 1 transaction, 64 bytes of memo. Per level: 1 transaction, 32 bytes of memo. No ledger
objects, no reserves. The reference checks the submitting node's Testnet network ID before signing.

## 10. Future work (not in scope now)

- **Metadata redaction:** EXIF fields (GPS, device serial, time) committed one by one with a salt each,
  disclosable or hidable per field like tiles.
- **Producer identity:** XRPL Credentials issued by the authority to producer accounts.
- **Chain of custody:** each descriptor names the anchor of the level it was made from, so a copy
  carries its whole history (authority → lab → newsroom). Prototyped and removed to keep the design
  small: it added a list to the sidecar, link checks to V4, and an attack surface (re-rooting a chain).
- **Sponsored anchoring (`Sponsor` amendment, Devnet only today):** the authority pays fees and reserves
  for downstream producers, so newsrooms anchor levels without holding XRP. xrpl-py 5.2 has
  `SponsorshipSet`; to be checked against its models before use. Not implemented: Devnet is reset
  periodically and live links would disappear.
- **Self-contained public copies (hybrid on-chain sidecar):** for a *public* copy only, publish its
  sidecar on XRPL (about 10.6 KB at 720p, so ~11 `AccountSet` transactions of ≤ 1 KB of memos each; the
  authority's public key travels in the trust list instead) and write a pointer to it in a PNG `tEXt`
  chunk, as ORIGO did in its JPEG comment. Anyone could then verify from the PNG alone. A wrong pointer
  can only lead to a REJECT. **Never for restricted copies:** whatever is on the ledger is public
  forever, and the salts of a restricted copy would expose tiles that public copies hide (§8.3).
- **Salt seed tree (GGM / puncturable PRF):** derive salts from a binary tree of seeds instead of
  `HMAC(K, i)`; revealing every visible tile then costs one seed per maximal visible subtree instead of
  32 bytes per tile (about 7 KB → a few hundred bytes for compact redactions). Makes the on-chain
  sidecar above fit in a handful of transactions. Needs sidecar format version 2.
- **Full ledger proofs:** check the transaction's inclusion in the ledger's transaction tree (SHAMap
  proof against `transaction_hash`) and the header against UNL validations, so a single honest-looking
  node needs no quorum.
- **Multi-resolution signing:** the authority also signs roots of 1/2 and 1/4 scale images, so a small
  public rendition can be verified without the full-size evidence.
- **Verifiable blur/pixelation** of hidden areas with zero-knowledge proofs (classical soundness).
- **Hardware keys:** ML-DSA in an HSM or smartcard (PKCS#11).

## 11. Build plan (one step at a time, review between steps)

| Step | Content | Network |
|---|---|---|
| 0 | This document, AGENTS.md, empty project skeleton, frontend spec | none |
| 1 | Pure core: PNG codec, tiles, salts, RFC 6962 Merkle, canonical JSON, manifest, ML-DSA, levels, recipe, strict sidecar, verify against an in-memory ledger. Unit tests + conformance vectors for the frontend (`tests/vectors/`) | none |
| 2 | XRPL layer: `submit()`, anchors, ledger reads (check xrpl-py 5.2 models and real `tx` responses); `bootstrap` (faucet, once); live proof of the manifest anchor | Testnet |
| 3 | CLI: `velum sign`, `velum derive`, `velum verify`; end-to-end demo AUTHORITY → LAB → NEWSROOM on the real 720p photo, plus attacks | Testnet |
