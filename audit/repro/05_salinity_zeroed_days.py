#!/usr/bin/env python
"""Repro: daily `so` (r20250912, raw and regrid; copied into r20251001) in 1999 and 2001
has steps whose time value is 0 (decodes to 1993-01-01 00:00), and blocks of steps whose
salinity is exactly 0.0 over the ocean, i.e. never written. The two overlap but not
exactly: some zero-stamped steps hold real data, and some zero-data steps have a valid
stamp. Reassigning a clean time axis (the current workaround) hides the zeroed data.
The newest release, r20260701, has neither problem; the script shows both releases.

Reads one 200x200 spatial chunk of the surface level; about 160 MB decompressed.

    python audit/repro/05_salinity_zeroed_days.py
"""

import cftime
import h5py
import numpy as np
import s3fs

P = "noaa-oar-cefi-regional-mom6-pds/northeast_pacific/full_domain/hindcast/daily/raw"
fs = s3fs.S3FileSystem(anon=True)


def runs(idx):
    """[3,4,5,9] -> '3-5, 9'"""
    out, start = [], None
    for a, b in zip(idx, list(idx[1:]) + [None]):
        start = a if start is None else start
        if b != a + 1:
            out.append(f"{start}-{a}" if start != a else f"{a}")
            start = None
    return ", ".join(out) or "none"


for rel, year in (("r20250912", 1999), ("r20250912", 2001), ("r20260701", 1999), ("r20260701", 2001)):
    key = f"{P}/{rel}/so.nep.full.hcast.daily.raw.{rel}.{year}01-{year}12.nc"
    with fs.open(key, "rb", block_size=2**22, cache_type="blockcache") as f, h5py.File(f) as h:
        t = h["time"]
        vals = t[...]
        units, cal = t.attrs["units"].decode(), t.attrs["calendar"].decode()
        so = h["so"]
        cy, cx = so.chunks[-2:]
        block = so[:, 0, 400:400 + cy, 200:200 + cx]
    ocean = block < 1e19  # land is the 1e20 fill value
    ocean_any = ocean.any(axis=0)
    zero_data = np.where([(block[i][ocean_any] == 0).all() for i in range(len(vals))])[0]
    zero_time = np.where(vals == 0)[0]
    print(f"{rel}/{key.rsplit('/', 1)[1]}")
    print(f"   time value 0 ({cftime.num2date(0, units, cal)}): steps {runs(zero_time)}")
    print(f"   salinity all 0.0 over ocean:        steps {runs(zero_data)}")
    both = np.intersect1d(zero_time, zero_data)
    print(f"   both: {len(both)}; zero stamp with real data: {len(np.setdiff1d(zero_time, zero_data))}; "
          f"zero data with valid stamp: {len(np.setdiff1d(zero_data, zero_time))}")
