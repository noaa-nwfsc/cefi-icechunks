#!/usr/bin/env python
"""For files with duplicated time stamps, check whether the data is duplicated too.

For each affected file, reads the primary variable over all time steps within
one spatial chunk (first level if 4-D) and compares each duplicated stamp with
the first occurrence of that stamp. Reading one spatial chunk rather than whole
slices keeps memory near one decompressed chunk (up to 160 MB for the daily
per-year files) instead of one per spatial tile.

Output: audit/out/dup_values.csv

    python audit/dup_values.py
"""

from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import s3fs

OUT = Path(__file__).parent / "out"


def main() -> None:
    files = pd.read_parquet(OUT / "files.parquet")
    axes = pd.read_parquet(OUT / "axes.parquet")
    t = axes[axes.vname == "time"].merge(files[["key", "group", "var"]], on="key")
    t["ndup"] = t["values"].map(lambda v: len(v) - len(set(v)))
    t = t[t.ndup > 0]
    print(f"{len(t)} files with duplicated time stamps")
    fs = s3fs.S3FileSystem(anon=True)
    rows = []
    for r in t.itertuples():
        vals = np.asarray(r.values)
        first_idx = {}
        pairs = []
        for i, v in enumerate(vals):
            if v in first_idx:
                pairs.append((first_idx[v], i))
            else:
                first_idx[v] = i
        try:
            with fs.open(r.key, "rb", block_size=2**22, cache_type="blockcache") as f, h5py.File(f, "r") as h:
                ds = h[r.var]
                cy, cx = ds.chunks[-2:]
                y0 = (ds.shape[-2] // 2 // cy) * cy  # the spatial chunk holding the domain centre
                x0 = (ds.shape[-1] // 2 // cx) * cx
                block = ds[(slice(None),) + (0,) * (ds.ndim - 3) + (slice(y0, y0 + cy), slice(x0, x0 + cx))]
                same = sum(np.array_equal(block[a], block[b], equal_nan=True) for a, b in pairs)
                bnds = h["time_bnds"][...] if "time_bnds" in h else None
                bnds_same = sum(np.array_equal(bnds[a], bnds[b]) for a, b in pairs) if bnds is not None else None
            rows.append({"group": r.group, "var": r.var, "file": Path(r.key).name, "ntime": len(vals),
                         "n_dup_stamps": len(pairs), "n_identical_data": int(same),
                         "n_identical_bounds": bnds_same, "dup_indices": json.dumps(pairs[:8])})
        except Exception as e:
            rows.append({"group": r.group, "var": r.var, "file": Path(r.key).name, "error": f"{type(e).__name__}: {e}"})
        print(rows[-1], flush=True)
    pd.DataFrame(rows).to_csv(OUT / "dup_values.csv", index=False)


if __name__ == "__main__":
    main()
