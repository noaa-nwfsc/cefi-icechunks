#!/usr/bin/env python
"""Flatten headers.jsonl into parquet tables for checks.py.

    files.parquet  one row per .nc: open error, format, global attrs
    vars.parquet   one row per (file, variable): dims, shape, dtype, chunks,
                   filters, fill value, units/calendar, hash of stored values
    axes.parquet   stored values of time-like 1-D axes and time bounds

Streams the JSONL so the multi-hundred-MB file never sits in memory whole.

    python audit/tables.py
"""

from __future__ import annotations

import json
from pathlib import Path

import hashlib

import numpy as np
import pandas as pd

OUT_DIR = Path(__file__).parent / "out"
AXIS_NAMES = {"time", "lead", "init", "time_bnds", "time_bounds", "member", "z_l", "z_i", "zl", "zi"}


def _s(v) -> str | None:
    return None if v is None else json.dumps(v)


def main() -> None:
    files, vars_, axes = [], [], []
    # pass 1: reruns append, so keep only the last record per key
    latest: dict[str, int] = {}
    with (OUT_DIR / "headers.jsonl").open() as fh:
        for i, line in enumerate(fh):
            latest[json.loads(line)["key"]] = i
    keep = set(latest.values())
    fh = (OUT_DIR / "headers.jsonl").open()
    for i, line in enumerate(fh):
        if i not in keep:
            continue
        r = json.loads(line)
        key = r["key"]
        ga = r.get("global_attrs") or {}
        files.append(
            {
                "key": key,
                "signature": r.get("signature"),
                "error": r.get("error"),
                "seconds": r.get("seconds"),
                "nvars": len(r.get("vars") or []),
                "groups": _s(r.get("groups")),
                "title": ga.get("title"),
                "global_attrs": _s(ga),
            }
        )
        for v in r.get("vars") or []:
            a = v.get("attrs") or {}
            short = v["name"].split("/")[-1]
            vals = v.get("values")
            vars_.append(
                {
                    "key": key,
                    "vname": v["name"],
                    "dims": _s(v.get("dims")),
                    "shape": _s(v.get("shape")),
                    "ndim": len(v.get("shape") or []),
                    "dtype": v.get("dtype"),
                    "layout": v.get("layout"),
                    "chunks": _s(v.get("chunks")),
                    "filters": _s(v.get("filters")),
                    "h5_fillvalue": _s(v.get("h5_fillvalue")),
                    "fill_attr": _s(a.get("_FillValue")),
                    "missing_value": _s(a.get("missing_value")),
                    "scale_factor": _s(a.get("scale_factor")),
                    "add_offset": _s(a.get("add_offset")),
                    "units": _s(a.get("units")),
                    "calendar": _s(a.get("calendar")),
                    "long_name": _s(a.get("long_name")),
                    "cell_measures": _s(a.get("cell_measures")),
                    "coordinates": _s(a.get("coordinates")),
                    "attrs": _s(a),
                    "values_sha1": v.get("values_sha1"),
                    # dtype-independent: float32 and float64 copies of one grid match
                    "values_hash": hashlib.sha1(np.round(np.asarray(vals, dtype="float64"), 4).tobytes()).hexdigest()[:12]
                    if vals else None,
                    "nvalues": len(vals) if vals is not None else None,
                    "first": vals[0] if vals else None,
                    "last": vals[-1] if vals else None,
                    "error": v.get("error"),
                }
            )
            if short in AXIS_NAMES and vals is not None:
                axes.append(
                    {
                        "key": key,
                        "vname": v["name"],
                        "units": a.get("units"),
                        "calendar": a.get("calendar"),
                        "values": vals,
                    }
                )
    fh.close()
    inv = pd.read_parquet(OUT_DIR / "inventory.parquet")
    pd.DataFrame(files).merge(inv, on="key", how="left").to_parquet(OUT_DIR / "files.parquet", index=False)
    pd.DataFrame(vars_).to_parquet(OUT_DIR / "vars.parquet", index=False)
    pd.DataFrame(axes).to_parquet(OUT_DIR / "axes.parquet", index=False)
    print(f"{len(files)} files, {len(vars_)} variables, {len(axes)} axes")


if __name__ == "__main__":
    main()
