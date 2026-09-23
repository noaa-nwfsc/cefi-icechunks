#!/usr/bin/env python
"""Repro: NWA monthly regrid r20250715 files are on two different longitude grids:
774 points from -98.44 at 0.0807 spacing (427 files) and 774 points from -98.0 at
0.0801 spacing (37 files). Variables on different grids can't share one group; the
0.0801 grid needs regridding, not just relabeling.

    python audit/repro/05_regrid_lon_grids.py
"""

import h5py
import s3fs

fs = s3fs.S3FileSystem(anon=True)
P = "noaa-oar-cefi-regional-mom6-pds/northwest_atlantic/full_domain/hindcast/monthly/regrid"
for rel, var in (("r20250715", "Heat_PmE"), ("r20250715", "thetao"), ("r20250715", "BMELT"), ("r20250715", "ALB")):
    d = f"{P}/{rel}"
    key = next(k for k in fs.ls(d) if k.rsplit("/", 1)[1].startswith(var + ".") and k.endswith(".nc"))
    with fs.open(key, "rb") as f, h5py.File(f) as h:
        lon = h["lon"][...]
        print(f"{rel} {var:9s} lon n={lon.size} first={lon[0]:.4f} last={lon[-1]:.4f} step={lon[1] - lon[0]:.4f}")
