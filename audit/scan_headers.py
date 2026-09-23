#!/usr/bin/env python
"""Read HDF5/netCDF metadata (no data variables) from every .nc in the inventory.

Writes one JSON line per file to audit/out/headers.jsonl. Re-running skips files
already recorded, so a dropped connection costs one file, not the run.

Per file: format signature, global attrs, open error.
Per variable: dims, shape, dtype, storage layout, chunks, filters, fill value,
attrs. For 1-D variables up to MAX_COORD_LEN long (time, lat, lon, z_l, bounds
flattened) the values themselves are stored, so time axes and grids can be
compared without reopening files.

    python audit/scan_headers.py [--workers 8] [--group-filter northeast_pacific]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import time
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

OUT_DIR = Path(__file__).parent / "out"
INVENTORY = OUT_DIR / "inventory.parquet"
HEADERS = OUT_DIR / "headers.jsonl"

MAX_COORD_LEN = 20000  # 1-D variables at most this long have their values stored
BOUNDS_NAMES = ("time_bnds", "time_bounds")
HASH_ONLY = ("average_T1", "average_T2", "average_DT")
GRID_NAMES = ("geolon", "geolat", "lon", "lat", "areacello", "deptho", "wet")

_fs = None


def _jsonable(v):
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    if isinstance(v, np.ndarray):
        return [_jsonable(x) for x in v.tolist()] if v.size < 50 else f"<array {v.shape}>"
    if isinstance(v, np.generic):
        return v.item()
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, float) and not np.isfinite(v):
        return str(v)
    return v


def _attrs(obj) -> dict:
    out = {}
    for k in obj.attrs:
        if k in ("DIMENSION_LIST", "REFERENCE_LIST", "_Netcdf4Dimid", "_Netcdf4Coordinates"):
            continue
        try:
            out[k] = _jsonable(obj.attrs[k])
        except Exception as e:  # unreadable attribute is itself a finding
            out[k] = f"<unreadable: {type(e).__name__}>"
    return out


def _dims(ds) -> list[str]:
    # a 1-D dimension scale (time, lat, ...) is its own dimension
    if ds.attrs.get("CLASS", b"") == b"DIMENSION_SCALE" and ds.ndim == 1:
        return [ds.name.lstrip("/")]
    names = []
    for i, dim in enumerate(ds.dims):
        try:
            names.append(dim[0].name.lstrip("/") if len(dim) else f"phony_dim_{i}")
        except Exception:
            names.append(f"phony_dim_{i}")
    return names


def _layout(ds) -> str:
    import h5py

    lay = ds.id.get_create_plist().get_layout()
    return {h5py.h5d.CHUNKED: "chunked", h5py.h5d.CONTIGUOUS: "contiguous", h5py.h5d.COMPACT: "compact"}.get(
        lay, str(lay)
    )


def _filters(ds) -> list:
    plist = ds.id.get_create_plist()
    out = []
    for i in range(plist.get_nfilters()):
        code, flags, opts, name = plist.get_filter(i)
        out.append([int(code), name.decode() if isinstance(name, bytes) else name, list(opts)])
    return out


def _scan_hdf5(f, rec: dict) -> None:
    import h5py

    with h5py.File(f, "r") as h:
        rec["global_attrs"] = _attrs(h)
        vars_ = []
        groups = []

        def visit(name, obj):
            if isinstance(obj, h5py.Group):
                groups.append(name)
                return
            if not isinstance(obj, h5py.Dataset):
                return
            v = {"name": name, "shape": list(obj.shape), "dtype": obj.dtype.str}
            try:
                v["dims"] = _dims(obj)
                v["layout"] = _layout(obj)
                v["chunks"] = list(obj.chunks) if obj.chunks else None
                v["filters"] = _filters(obj)
                v["h5_fillvalue"] = _jsonable(obj.fillvalue)
                v["attrs"] = _attrs(obj)
                v["is_dimension_scale"] = obj.attrs.get("CLASS", b"") == b"DIMENSION_SCALE"
                _values(v, obj, name.split("/")[-1])
            except Exception as e:
                v["error"] = f"{type(e).__name__}: {e}"
            vars_.append(v)

        # not h.visititems: H5Ovisit collects storage info that walks every chunk
        # index, which costs thousands of range reads on files with small chunks
        def walk(g, prefix=""):
            for name in g:
                obj = g[name]
                visit(prefix + name, obj)
                if isinstance(obj, h5py.Group):
                    walk(obj, prefix + name + "/")

        walk(h)
        rec["vars"] = vars_
        rec["groups"] = groups


def _scan_netcdf3(f, rec: dict) -> None:
    from scipy.io import netcdf_file

    nc = netcdf_file(f, "r", mmap=False)
    try:
        rec["global_attrs"] = {k: _jsonable(v) for k, v in nc._attributes.items()}
        rec["netcdf3_version"] = nc.version_byte
        vars_ = []
        for name, var in nc.variables.items():
            v = {
                "name": name,
                "shape": list(var.shape),
                "dtype": var.data.dtype.str,
                "dims": list(var.dimensions),
                "layout": "netcdf3",
                "chunks": None,
                "filters": [],
                "attrs": {k: _jsonable(a) for k, a in var._attributes.items()},
                "is_dimension_scale": var.dimensions == (name,),
            }
            _values(v, var.data, name)
            vars_.append(v)
        rec["vars"] = vars_
        rec["groups"] = []
    finally:
        nc.close()


def _values(v: dict, arr, short: str) -> None:
    """Store small 1-D coordinate values, and hashes of 2-D grid arrays."""
    shape = arr.shape
    n = int(np.prod(shape)) if shape else 1
    kind = arr.dtype.kind
    small = len(shape) == 1 and n <= MAX_COORD_LEN
    bounds = short in BOUNDS_NAMES and n <= 2 * MAX_COORD_LEN
    if (small or bounds) and kind in "fiu":
        vals = np.asarray(arr[...])
        if short not in HASH_ONLY:
            v["values"] = [x if np.isfinite(x) else None for x in vals.ravel().astype("float64").tolist()]
        v["values_sha1"] = hashlib.sha1(np.ascontiguousarray(vals).tobytes()).hexdigest()
    elif kind in "fiu" and len(shape) == 2 and n <= 4_000_000 and min(shape) > 1 and short in GRID_NAMES:
        vals = np.asarray(arr[...])
        v["values_sha1"] = hashlib.sha1(np.ascontiguousarray(vals).tobytes()).hexdigest()


def scan_one(key: str) -> dict:
    import s3fs

    global _fs
    if _fs is None:
        # a few reads stall for many minutes without these
        _fs = s3fs.S3FileSystem(
            anon=True,
            config_kwargs={
                "connect_timeout": 20,
                "read_timeout": 60,
                "retries": {"max_attempts": 5, "mode": "standard"},
            },
        )
    rec = {"key": key, "t0": time.time()}
    try:
        with _fs.open(key, "rb", block_size=2**20, cache_type="blockcache") as f:
            sig = f.read(8)
            rec["signature"] = (
                "hdf5" if sig.startswith(b"\x89HDF") else "netcdf3" if sig[:3] == b"CDF" else repr(sig)
            )
            f.seek(0)
            if rec["signature"] == "hdf5":
                _scan_hdf5(f, rec)
            elif rec["signature"] == "netcdf3":
                _scan_netcdf3(f, rec)
            else:
                rec["error"] = f"unknown file signature {rec['signature']}"
    except Exception as e:
        rec["error"] = f"{type(e).__name__}: {e}"
        rec["traceback"] = traceback.format_exc(limit=3)
    rec["seconds"] = round(time.time() - rec.pop("t0"), 2)
    return rec



def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--group-filter", default="", help="substring of the group path")
    p.add_argument("--limit", type=int, default=0)
    args = p.parse_args()

    inv = pd.read_parquet(INVENTORY)
    keys = inv[(inv.ext == "nc") & inv.group.fillna("").str.contains(args.group_filter)].key.tolist()
    done = set()
    if HEADERS.exists():
        with HEADERS.open() as fh:
            for line in fh:
                r = json.loads(line)
                if "error" not in r and "seconds" in r:  # retry failures and old netcdf3 stubs
                    done.add(r["key"])
    todo = [k for k in keys if k not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(keys)} nc files, {len(done)} done, {len(todo)} to scan", flush=True)

    ctx = mp.get_context("spawn")
    t = time.time()
    with ctx.Pool(args.workers, maxtasksperchild=200) as pool, HEADERS.open("a") as out:
        for i, rec in enumerate(pool.imap_unordered(scan_one, todo, chunksize=1), 1):
            out.write(json.dumps(rec, default=lambda o: o.item() if hasattr(o, "item") else str(o)) + "\n")
            out.flush()
            if i % 100 == 0 or "error" in rec:
                print(f"{i}/{len(todo)} {time.time() - t:.0f}s {rec['key'].rsplit('/', 1)[-1]} {rec.get('error', '')}", flush=True)
    print(f"done in {time.time() - t:.0f}s")


if __name__ == "__main__":
    main()
