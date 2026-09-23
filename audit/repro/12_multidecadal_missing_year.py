#!/usr/bin/env python
"""Repro: NWA multi-decadal outlook T_adx for SSP585 has 130 yearly steps with a two-year
jump, while every other variable/scenario has 131 (1970-2100).

    python audit/repro/12_multidecadal_missing_year.py
"""

import cftime
import h5py
import numpy as np
import s3fs

fs = s3fs.S3FileSystem(anon=True)
D = "noaa-oar-cefi-regional-mom6-pds/northwest_atlantic/full_domain/multi_decadal_outlook/yearly/raw/r20260331"
for var, ssp in (("T_adx", "SSP585"), ("T_adx", "SSP245"), ("MLD_003", "SSP585")):
    key = f"{D}/{var}.nwa.full.multi_decade.yearly.raw.r20260331.{ssp}.1970-2100.nc"
    with fs.open(key, "rb") as f, h5py.File(f) as h:
        t = h["time"]
        vals = t[...]
        d = cftime.num2date(vals, t.attrs["units"].decode(), t.attrs["calendar"].decode())
        gap = np.where(np.diff(vals) > 367)[0]
        print(f"{var} {ssp}: {len(vals)} steps {d[0].year}..{d[-1].year}"
              + (f"; gap after {d[gap[0]].year} -> {d[gap[0] + 1].year}" if len(gap) else ""))
