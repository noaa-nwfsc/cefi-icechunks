#!/usr/bin/env python
"""Repro: in NEP monthly r20250912, 110 raw (92 regrid) variables have 396 time steps whose
last six months repeat Jan-Jun 2025; the other ~360 variables have a clean 390-step axis.
sisnmass's time axis is broken more badly (71 duplicated stamps, ends at 1993-01-01).

    python audit/repro/04_monthly_duplicated_tail.py
"""

import cftime
import h5py
import numpy as np
import s3fs

D = "noaa-oar-cefi-regional-mom6-pds/northeast_pacific/full_domain/hindcast/monthly/raw/r20250912"
fs = s3fs.S3FileSystem(anon=True)


def show(var):
    with fs.open(f"{D}/{var}.nep.full.hcast.monthly.raw.r20250912.199301-202506.nc", "rb") as f, h5py.File(f) as h:
        t = h["time"]
        vals = t[...]
        dates = cftime.num2date(vals, t.attrs["units"].decode(), t.attrs["calendar"].decode())
    dup = len(vals) - len(np.unique(vals))
    print(f"{var}: {len(vals)} steps, {dup} duplicated stamps")
    print("   last 8:", [d.strftime("%Y-%m-%d") for d in dates[-8:]])


for v in ("chlos", "tos", "sisnmass"):
    show(v)
