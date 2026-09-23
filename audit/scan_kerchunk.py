#!/usr/bin/env python
"""Summarize every Kerchunk .json CEFI publishes beside the NetCDFs.

Writes one JSON line per .json object to audit/out/kerchunk.jsonl: parse errors,
reference-format version, which files the references point at, and per variable
the .zarray metadata (shape, chunks, dtype, compressor, filters, fill_value) plus
the number of chunk references. Whether the byte ranges are right is checked
by smoke_virtualizarr.py, against VirtualiZarr's own manifest.

    python audit/scan_kerchunk.py [--workers 4]
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import time
from pathlib import Path

import pandas as pd

OUT_DIR = Path(__file__).parent / "out"
INVENTORY = OUT_DIR / "inventory.parquet"
KERCHUNK = OUT_DIR / "kerchunk.jsonl"

_fs = None


def _get_fs():
    global _fs
    if _fs is None:
        import s3fs

        _fs = s3fs.S3FileSystem(anon=True)
    return _fs


def scan_one(key: str) -> dict:
    rec = {"key": key}
    try:
        raw = _get_fs().cat(key)
        rec["bytes"] = len(raw)
        if not raw:
            rec["error"] = "empty object"
            return rec
        d = json.loads(raw)
    except Exception as e:
        rec["error"] = f"{type(e).__name__}: {e}"
        return rec
    rec["version"] = d.get("version")
    refs = d.get("refs", d if "version" not in d else {})
    rec["templates"] = d.get("templates")
    urls: dict[str, int] = {}
    vars_: dict[str, dict] = {}
    n_inline = 0
    for k, v in refs.items():
        name, _, leaf = k.rpartition("/")
        if leaf == ".zarray":
            za = json.loads(v) if isinstance(v, str) else v
            vars_.setdefault(name, {})["zarray"] = za
        elif leaf == ".zattrs":
            za = json.loads(v) if isinstance(v, str) else v
            vars_.setdefault(name, {})["dims"] = za.get("_ARRAY_DIMENSIONS")
        elif leaf.startswith("."):
            continue
        elif isinstance(v, list):
            vars_.setdefault(name, {}).setdefault("nrefs", 0)
            vars_[name]["nrefs"] += 1
            urls[v[0]] = urls.get(v[0], 0) + 1
        else:
            n_inline += 1
            vars_.setdefault(name, {}).setdefault("ninline", 0)
            vars_[name]["ninline"] += 1
    rec["urls"] = urls
    rec["n_inline"] = n_inline
    rec["vars"] = vars_
    return rec


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--workers", type=int, default=4)
    args = p.parse_args()
    inv = pd.read_parquet(INVENTORY)
    ctx = mp.get_context("spawn")
    t = time.time()

    keys = inv[inv.ext == "json"].key.tolist()
    done = set()
    if KERCHUNK.exists():
        done = {json.loads(l)["key"] for l in KERCHUNK.open()}
    todo = [k for k in keys if k not in done]
    print(f"{len(keys)} json, {len(todo)} to scan", flush=True)
    with ctx.Pool(args.workers) as pool, KERCHUNK.open("a") as out:
        for i, rec in enumerate(pool.imap_unordered(scan_one, todo, chunksize=4), 1):
            out.write(json.dumps(rec) + "\n")
            if i % 500 == 0:
                print(f"{i}/{len(todo)} {time.time() - t:.0f}s", flush=True)


if __name__ == "__main__":
    main()
