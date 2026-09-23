#!/usr/bin/env python
"""Repro: problems specific to PCI monthly raw r20260427.
  - T_adx_2d: time has length 0 and no units, T_adx_2d is [0, 539, 726], xq/yh are all zeros,
    yet its Kerchunk JSON still describes 396 time steps (the NetCDF changed after the JSON).
  - speed: the file has no `speed` variable at all, and xh/yh are all zeros.
  - ffedet_btm: the data variable is empty, shape [0, 539, 725], and xh/yh are all zeros.
  - average_DT chunk [512] (and time_bnds chunk [800, 2] where present) exceed the 396-step axis,
    which VirtualiZarr accepts for reading but refuses to concatenate.

    python audit/repro/10_pacific_islands_broken_files.py
"""

import json

import h5py
import s3fs

fs = s3fs.S3FileSystem(anon=True)
D = "noaa-oar-cefi-regional-mom6-pds/pacific_islands/full_domain/hindcast/monthly/raw/r20260427"


def summarize(var):
    key = f"{D}/{var}.pci.full.hcast.monthly.raw.r20260427.199301-202512.nc"
    with fs.open(key, "rb") as f, h5py.File(f) as h:
        print(f"{var}: variables {sorted(h)}")
        for c in ("time", "xh", "yh", "xq"):
            if c in h:
                v = h[c][...]
                units = h[c].attrs.get("units")
                print(f"   {c}: n={v.size} min={v.min() if v.size else '-'} max={v.max() if v.size else '-'} units={units!r}")
        if var in h:
            print(f"   {var}: shape {h[var].shape} chunks {h[var].chunks}")
        for c in ("time_bnds", "average_DT"):
            if c in h:
                print(f"   {c}: shape {h[c].shape} chunks {h[c].chunks}")
    return key


key = summarize("T_adx_2d")
refs = json.loads(fs.cat(key[:-3] + ".json"))["refs"]
print(f"   Kerchunk JSON says T_adx_2d shape {json.loads(refs['T_adx_2d/.zarray'])['shape']}")
summarize("speed")
summarize("ffedet_btm")
