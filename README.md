# VELUM

Verifiable multi-level redaction of authority-signed images, anchored on the XRP Ledger.

An authority signs a photo once (ML-DSA-44, post-quantum) over a Merkle tree of salted 64×64 tiles.
Anyone holding a copy can black out more tiles and republish it; every copy, at every level of
redaction, is verifiable by anyone against the authority's signature and its XRPL anchors.

Design: [`docs/VELUM.md`](docs/VELUM.md) · Frontend: [`docs/frontend-spec.md`](docs/frontend-spec.md)

## Run (XRPL Testnet)

```bash
make setup       # venv + dependencies
make bootstrap   # fund AUTHORITY, LAB, NEWSROOM once (faucet) -> .env.local, trust.local.json
make demo        # THE CASE OF THE MISSING PIZZA, live on Testnet
make check       # typecheck + offline tests
```

## Web app: Viewer, Editor, embed widget

```bash
make web-setup   # npm ci (pinned lockfile, no install scripts)
make web-demo    # copy the files of the last `make demo` into the Viewer's samples + trust list
make web         # http://localhost:3000
```

The Viewer verifies any VELUM PNG in the browser (Web Worker, ML-DSA-44, 2 of 3 Testnet nodes); the
Editor redacts a verified copy further and anchors it with a wallet extension (Xaman, GemWallet,
WalletConnect); the widget adds a "Check" badge to `<img data-velum-evidence="…">`. `make check` runs
its typecheck and tests too, against the same vectors as the Python code.

## The demo: The Case of the Missing Pizza

Exhibit A (`samples/missing_pizza_case.png`): a hackathon desk, an empty pizza box, a suspiciously
happy suspect and a note that says *Secret Passwd: 4*.

| Copy | Made by | Blacked out | For |
|---|---|---|---|
| `l0` | the authority ("Department of Hackathon Integrity") | nothing | the judges |
| `l1` | LAB | the password note | analysts |
| `l2` + `l2.public.png` | NEWSROOM | also the suspect's face; shrunk to 640×360 | everyone |

Every copy verifies against the authority's ML-DSA-44 signature and its XRPL anchors. Then three
forgeries are rejected: a pizza painted back into the public image (V6), the original face pasted
over the black tiles (V3), and a manifest re-signed with another key (V1, V2).
*You can hide the truth. You can't fake it.*

Live run (2026-11-21, Testnet):

- authority manifest anchor: <https://testnet.xrpl.org/transactions/2428ADA601DF6EA9D5B21E7902575F96A64F4D37FD713EB0ECF28D95AC5007F0>
- L0 by the authority: <https://testnet.xrpl.org/transactions/044475E29AD1D485D713884A85756286F09A28B733F695400DEA0CBD9D15B626>
- L1 by LAB: <https://testnet.xrpl.org/transactions/93247FA36AE67D35FA139EFC0495227F626457C3CAA18C34F12AC265A6C14239>
- L2 by NEWSROOM: <https://testnet.xrpl.org/transactions/BCB977F2E05A5100EE87024ADF4CDE5A2C0B0F9EF56AB8680AB1AA0009190E26>

## Command line

```bash
velum sign   samples/photo.png --out out/case --name l0                       # authority (AUTHORITY wallet)
velum derive out/case/l0 --as LAB --name l1 --hide-rect 8:9:10:10             # tiles col0:row0:col1:row1
velum derive out/case/l1 --as NEWSROOM --name l2 --hide 6,7,8 --resize 640x360 --brightness 8
velum verify out/case/l2                                                      # exit 0 ACCEPT, 1 REJECT, 3 UNVERIFIABLE
```

Exit codes: 0 ACCEPT, 1 REJECT, 2 usage error, 3 UNVERIFIABLE (retry), 4 other error. Existing files
are never overwritten without `--force`; the tile grid is checked (no silent wrap-around).

- The authority's per-image secret `K` is written to a private folder (`~/.velum/masters`, or
  `VELUM_MASTER_DIR`), never next to the level files you share. It is never deleted: `sign --force`
  refuses to touch it unless `--replace-master` is given, which moves the old one aside.
- `derive` verifies its source first (`--trust`, default `trust.local.json`) and refuses anything but ACCEPT.
- `verify` does not believe a single XRPL node: it asks the nodes in `XRPL_RPC_URLS`, recomputes the
  transaction and ledger hashes, and needs `XRPL_QUORUM` distinct endpoints (default 2) to agree.
  URLs sharing a host and port count once. Configure independently operated nodes (see `.env.example`).
- Bootstrap creates `trust.local.json` on first use and preserves existing trust lists, including revocations.

`make prove` runs the smaller step-2 proof on a synthetic image.

## Licensing and credits

VELUM's code and documentation currently have no project license. Third-party packages retain
their own licenses. The application installs [xrpl-py 5.2.0](https://pypi.org/project/xrpl-py/5.2.0/)
(ISC) and [dilithium-py 1.5.1](https://pypi.org/project/dilithium-py/1.5.1/) (MIT license in
the wheel). The development tools [pytest](https://pypi.org/project/pytest/9.2.0/) and
[mypy](https://pypi.org/project/mypy/2.4.1/) use MIT. When redistributing a bundled environment,
include the applicable notices from the installed distributions and their dependencies.

The demo uses [missing_pizza_case.png](samples/missing_pizza_case.png). Its embedded metadata
identifies Canva as the editing tool. The creator and redistribution terms are undocumented.
The terminal banner was rendered using the [FIGlet Small font](https://github.com/cmatsuoka/figlet/blob/master/fonts/small.flf)
by Glenn Chappell, with modifications by Paul Burton.
