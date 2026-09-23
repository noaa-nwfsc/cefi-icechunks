#!/usr/bin/env python
"""Repro: in NEP daily r20250912, chlos and phycos run to 2025-08-22 while every other
variable stops at 2025-06-30, and their files use different time chunks (29 and 37)
from each other across years. The 2025 files are all named ...202501-202512.

    python audit/repro/06_daily_series_end_dates.py
"""

import cftime
import h5py
import s3fs

D = "noaa-oar-cefi-regional-mom6-pds/northeast_pacific/full_domain/hindcast/daily/raw/r20250912"
fs = s3fs.S3FileSystem(anon=True)

for var, span in (("dissic", "202501-202506"), ("chlos", "202501-202512"), ("phycos", "202501-202512"),
                  ("chlos", "199301-199312")):
    key = f"{D}/{var}.nep.full.hcast.daily.raw.r20250912.{span}.nc"
    if not fs.exists(key):
        print(f"{key.rsplit('/', 1)[1]}: not present")
        continue
    with fs.open(key, "rb") as f, h5py.File(f) as h:
        t = h["time"]
        d = cftime.num2date(t[[0, -1]], t.attrs["units"].decode(), t.attrs["calendar"].decode())
        print(f"{key.rsplit('/', 1)[1]}: {t.shape[0]} steps {d[0]:%Y-%m-%d}..{d[1]:%Y-%m-%d}, "
              f"{var} chunks {h[var].chunks}")
