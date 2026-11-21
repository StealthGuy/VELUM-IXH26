"""VELUM: verifiable multi-level redaction of authority-signed images, anchored on the XRP Ledger.

Design: docs/VELUM.md. Build step 1 (pure and offline):

    image       Image: 8-bit RGB pixels in memory
    png         read_png (any valid PNG VELUM accepts; strict for the verifier) / write_png (uncompressed,
                with the sidecar embedded in a zTXt chunk) / read_sidecar
    tiles       64-pixel grid, zero padding, salts (HMAC of K), leaf hashes
    merkle      RFC 6962 root over leaf hashes
    canonical   canonical JSON bytes, strict JSON parsing
    schema      strict typed readers for parsed JSON
    pq          ML-DSA-44 keys, sign, verify, fingerprint
    manifest    what the authority signs and anchors
    descriptor  what the producer of a copy anchors: hidden bitmap, crop, recipe
    sidecar     the sidecar, strictly parsed (embedded in the PNG; NAME.velum.json only as a fallback)
    level       commit an image, release copies from the master or from another copy
    recipe      rendition: crop, rotate, resize, brightness/contrast
    ledger      the interface to validated XRPL history (implemented in step 2)
    trust       the verifier's trust list
    verify      checks V1-V6: ACCEPT / REJECT / UNVERIFIABLE

Build step 2 (XRPL Testnet):

    config      settings from .env, secrets from .env.local (never printed)
    xrpl_ledger submit() and anchor(): the only writes; XrplLedger: the real LedgerView, from a quorum of nodes

Build step 3:

    cli         velum sign | derive | verify
"""

__version__ = "0.1.0"
