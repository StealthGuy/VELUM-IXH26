# AGENTS.md — VELUM

Rules for every coding agent working in this repository. `CLAUDE.md` only imports this file.
The design is `docs/VELUM.md`: read it before touching code, and change it first if the design changes.

## 0. Snapshot

- **Project:** VELUM, verifiable multi-level redaction of authority-signed images, anchored on XRPL.
- **Track:** IXH26 Track 1, Advanced Cryptography for Blockchain.
- **Network:** XRPL **Testnet**. XRPL is mandatory: every manifest and every level is anchored.
- **Stack:** Python ≥ 3.10, `xrpl-py` 5.2, `dilithium-py` (ML-DSA-44), standard library for everything
  else (PNG, hashing, HMAC). No Pillow, no lossy formats. The web app in `web/` (Nuxt 3, TypeScript,
  by lmvjack, imported with `git subtree`) is a second implementation of the verifier and the
  producer role, specified by `docs/frontend-spec.md` and held to the same vectors (`make web-test`).
- **Language:** code, comments, docs and CLI output in English (US).

## 1. Hard rules

1. **No mocks of ledger data.** Never fake tx hashes, ledger times or `tesSUCCESS`, not even as a
   fallback. On failure, raise. In-memory ledgers exist only in `tests/`.
2. **Secrets stay in `.env.local`** (XRPL seeds, the authority's ML-DSA seed) and in `*.master.json`
   (the per-image salt secret `K`, chmod 600, gitignored). They are never printed, logged, committed,
   or passed on the command line.
3. **One way to submit.** Every transaction goes through `velum.xrpl_ledger.submit()` (anchors through
   `velum.xrpl_ledger.anchor()`). Nothing else calls xrpl-py's submit/sign functions.
4. **The faucet is called only by `make bootstrap`**, once. Scripts and tests load existing wallets.
5. **Integer arithmetic only** in anything that produces or checks pixels. No floats: every machine
   must compute identical pixels.
6. **Fail closed.** A verifier error is a REJECT with a reason, never a pass.

## 2. Commands

| Command | What it does |
| --- | --- |
| `make setup` | creates `.venv`, installs the package with dev tools (`pip install -e .[dev]`) |
| `make test` | offline unit tests |
| `make check` | `mypy` + tests; run before every commit |
| `make bootstrap` | funds AUTHORITY, LAB, NEWSROOM on Testnet **once** (the only faucet caller), creates the authority's ML-DSA seed, writes `trust.local.json` |
| `make prove` | live proof of step 2: anchors on Testnet, verification against the real ledger |
| `make demo` | THE CASE OF THE MISSING PIZZA: sign, two redacted copies, verification and three forgeries, live |
| `velum sign / derive / verify` | the command line (`src/velum/cli.py`); see README |

## 3. Don't guess the SDK

Before using an XRPL transaction, field or request, open its model under `xrpl/models/` in the
installed xrpl-py and use the exact class and snake_case field names. If it is not there, stop and ask
the human; never build raw JSON around a missing model.

## 4. XRPL checklist

- Anchors are `AccountSet` transactions with exactly one memo; memo type and data are hex.
- Only trust **validated** ledgers and `tesSUCCESS` results; read times from the validated ledger's
  `close_time` (Ripple epoch, add 946684800 for Unix time).
- Check needed amendments on the network before relying on them.

## 5. Layout

```text
docs/VELUM.md     the design: formats, predicate, threat model
src/velum/        the package (pure core first, XRPL layer separate)
tests/            offline tests and test vectors
scripts/          bootstrap and live proofs (from step 2)
samples/          input images
```

## 6. Workflow

1. The human reviews between steps. Do one step of the build plan (`docs/VELUM.md` §11) at a time,
   then stop and summarize which files to read.
2. Keep modules small and readable: the author must be able to follow every line.
3. Ask before adding a dependency.
4. Before committing: `make check` passes, `git status` shows no `.env*`, small commits with a prefix
   (`feat(tiles): …`, `fix(verify): …`, `docs: …`).

## Web app (`web/`)

- It must give the same verdict as `velum.verify` on every vector: `web/tests` read `tests/vectors`
  and `tests/fixtures` directly. Change a format in Python and `docs/VELUM.md` first, regenerate the
  vectors, then port.
- It never holds a secret: wallet extensions sign, the browser sees no seed. It never calls the
  faucet; `make web-demo` only copies the files of the last `make demo`.
- It verifies against the real ledger only (2 of 3 Testnet nodes, hashes recomputed, like
  `velum.xrpl_ledger`). `MemoryLedger` exists only for `web/tests`.
- Ask before adding an npm dependency; `npm ci --ignore-scripts` (`make web-setup`) is the install.
