#!/usr/bin/env python
"""Repro: NWA monthly regrid files are on different longitude grids: 774 points from
-98.44 at 0.0807 spacing, 774 points from -98.0 at 0.0801 spacing, and (r20230520)
the first grid again but labelled 0-360 (261.56). Variables on different grids can't
share one group; the 0.0801 grid needs regridding, not just relabeling.

    python audit/repro/09_regrid_lon_conventions.py
"""

import h5py
import s3fs

fs = s3fs.S3FileSystem(anon=True)
P = "noaa-oar-cefi-regional-mom6-pds/northwest_atlantic/full_domain/hindcast/monthly/regrid"
for rel, var in (("r20250715", "Heat_PmE"), ("r20250715", "BMELT"),
                 ("r20230520", "Heat_PmE"), ("r20230520", "ALB"), ("r20230520", "MLD_003")):
    d = f"{P}/{rel}"
    key = next(k for k in fs.ls(d) if k.rsplit("/", 1)[1].startswith(var + ".") and k.endswith(".nc"))
    with fs.open(key, "rb") as f, h5py.File(f) as h:
        lon = h["lon"][...]
        print(f"{rel} {var:9s} lon n={lon.size} first={lon[0]:.4f} last={lon[-1]:.4f} step={lon[1] - lon[0]:.4f}")
