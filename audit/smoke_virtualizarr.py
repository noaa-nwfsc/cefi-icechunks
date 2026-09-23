#!/usr/bin/env python
"""Parse a sample of NetCDFs with VirtualiZarr and compare to Kerchunk.

Sample: per release directory, one file per distinct primary-variable signature,
topped up to PER_GROUP files. For each sampled file:
  1. open_virtual_dataset with HDFParser (netCDF3 files are expected to fail;
     that failure is recorded, not hidden)
  2. for every variable, compare VirtualiZarr's chunk manifest (path, offset,
     length per chunk) against the Kerchunk JSON that references this file,
     found by the URL inside the JSON, not by its (sometimes misnamed) filename.

Output: audit/out/smoke.jsonl, one line per sampled file. Resumable.

    python audit/smoke_virtualizarr.py [--workers 4]
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import time
import traceback
from pathlib import Path

import pandas as pd

OUT = Path(__file__).parent / "out"
SMOKE = OUT / "smoke.jsonl"
BUCKET = "noaa-oar-cefi-regional-mom6-pds"
B = f"s3://{BUCKET}"
PER_GROUP = 20

_state: dict = {}


def _setup():
    if not _state:
        import s3fs
        from obspec_utils.registry import ObjectStoreRegistry
        from obstore.store import from_url
        from virtualizarr.parsers import HDFParser

        store = from_url(B, region="us-east-1", skip_signature=True)
        _state["registry"] = ObjectStoreRegistry({B: store})
        _state["parser"] = HDFParser()
        _state["fs"] = s3fs.S3FileSystem(
            anon=True, config_kwargs={"connect_timeout": 20, "read_timeout": 60, "retries": {"max_attempts": 5}}
        )
    return _state


def _norm(p: str) -> str:
    return p.replace("s3://", "")


def smoke_one(task: tuple[str, str | None]) -> dict:
    from virtualizarr import open_virtual_dataset
    from virtualizarr.manifests import ManifestArray

    nc_key, json_key = task
    st = _setup()
    rec = {"key": nc_key, "json_key": json_key, "t0": time.time()}
    try:
        vds = open_virtual_dataset(
            url=f"s3://{nc_key}", parser=st["parser"], registry=st["registry"], loadable_variables=[]
        )
        rec["vz_vars"] = sorted(vds.variables)
        manifests = {}
        for name, v in vds.variables.items():
            if isinstance(v.data, ManifestArray):
                manifests[name] = v.data
        rec["codecs"] = {
            n: [type(c).__name__ + (json.dumps(getattr(c, "codec_config", {}) or {}, sort_keys=True)) for c in m.metadata.codecs]
            for n, m in manifests.items()
        }
    except Exception as e:
        rec["vz_error"] = f"{type(e).__name__}: {str(e)[:500]}"
        rec["vz_traceback"] = traceback.format_exc(limit=4)[-1500:]
        manifests = None

    if json_key and manifests is not None:
        try:
            refs = json.loads(st["fs"].cat(json_key))["refs"]
            kvars: dict[str, dict] = {}
            for k, v in refs.items():
                name, _, leaf = k.rpartition("/")
                if leaf.startswith(".") or not name:
                    continue
                kvars.setdefault(name, {})[leaf] = v
            cmp = {}
            for name, ma in manifests.items():
                vz = ma.manifest.dict()
                kc = kvars.get(name)
                if kc is None:
                    cmp[name] = "missing-in-json"
                    continue
                bad = inlined = 0
                examples = []
                for cid, e in vz.items():
                    # scalars: VirtualiZarr's chunk key is "" where Kerchunk writes "0"
                    r = kc.get(cid if cid else "0")
                    if isinstance(r, str):  # Kerchunk inlines small chunks as base64; legitimate
                        inlined += 1
                        continue
                    if not isinstance(r, list) or _norm(r[0]) != _norm(e["path"]) or r[1] != e["offset"] or r[2] != e["length"]:
                        bad += 1
                        if len(examples) < 3:
                            examples.append([cid, [e["offset"], e["length"]], r[1:] if isinstance(r, list) else str(r)[:40]])
                extra = len(set(kc) - {c if c else "0" for c in vz})
                zarray = refs.get(f"{name}/.zarray")
                za = json.loads(zarray) if isinstance(zarray, str) else zarray or {}
                meta_diff = []
                if za and list(za.get("chunks", [])) != list(ma.metadata.chunk_grid.chunk_shape):
                    meta_diff.append(f"chunks json {za.get('chunks')} vs nc {list(ma.metadata.chunk_grid.chunk_shape)}")
                if za and list(za.get("shape", [])) != list(ma.shape):
                    meta_diff.append(f"shape json {za.get('shape')} vs nc {list(ma.shape)}")
                if bad or extra or meta_diff:
                    cmp[name] = {"n_vz": len(vz), "n_bad": bad, "n_inlined": inlined, "n_extra_in_json": extra, "examples": examples,
                                 "meta": meta_diff}
            rec["json_only_vars"] = sorted(set(kvars) - set(manifests) - set(rec.get("vz_vars", [])))
            rec["kerchunk_diff"] = cmp
        except Exception as e:
            rec["json_error"] = f"{type(e).__name__}: {e}"
    rec["seconds"] = round(time.time() - rec.pop("t0"), 2)
    return rec


def tasks() -> list[tuple[str, str | None]]:
    inv = pd.read_parquet(OUT / "inventory.parquet")
    nc = inv[inv.ext == "nc"].copy()
    # map nc -> the json that actually references it (single-file jsons only)
    ref_by_nc = {}
    for line in (OUT / "kerchunk.jsonl").open():
        r = json.loads(line)
        us = list(r.get("urls") or {})
        if len(us) == 1:
            ref_by_nc.setdefault(_norm(us[0]), r["key"])
    nc["var"] = nc["var"].fillna(nc.name.str.replace(".nc", "", regex=False))
    first = nc.sort_values("key").groupby(["group", "var"]).head(1)
    # Parser failures follow how a file was written, not which variable it holds, so
    # per group take one file per distinct primary-variable signature, then top up
    # to PER_GROUP files. Every (group, var) would be ~6,500 files and ~3 hours.
    files = pd.read_parquet(OUT / "files.parquet")[["key", "signature"]]
    vars_ = pd.read_parquet(OUT / "vars.parquet")[["key", "vname", "dims", "dtype", "filters", "chunks", "layout"]]
    first = first.merge(files, on="key", how="left").merge(
        vars_, left_on=["key", "var"], right_on=["key", "vname"], how="left"
    )
    first["sig"] = (
        first.signature.astype(str) + first.dims.astype(str) + first.dtype.astype(str) + first.filters.astype(str)
        + first.layout.astype(str) + first.chunks.map(lambda c: str(len(json.loads(c))) if isinstance(c, str) else "-")
    )
    picked = []
    for _, g in first.groupby("group"):
        sig = g.drop_duplicates("sig")
        rest = g[~g.key.isin(sig.key)]
        picked.append(pd.concat([sig, rest.head(max(0, PER_GROUP - len(sig)))]))
    sample = pd.concat(picked)
    return [(k, ref_by_nc.get(k)) for k in sample.key]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--workers", type=int, default=4)
    args = p.parse_args()
    todo = tasks()
    done = {json.loads(l)["key"] for l in SMOKE.open()} if SMOKE.exists() else set()
    todo = [t for t in todo if t[0] not in done]
    print(f"{len(todo)} files to smoke-test", flush=True)
    t = time.time()
    with mp.get_context("spawn").Pool(args.workers, maxtasksperchild=100) as pool, SMOKE.open("a") as out:
        for i, rec in enumerate(pool.imap_unordered(smoke_one, todo), 1):
            out.write(json.dumps(rec, default=str) + "\n")
            out.flush()
            if i % 100 == 0:
                print(f"{i}/{len(todo)} {time.time() - t:.0f}s", flush=True)
    print(f"done in {time.time() - t:.0f}s")


if __name__ == "__main__":
    main()
