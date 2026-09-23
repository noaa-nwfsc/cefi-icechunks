#!/usr/bin/env python
"""Repro: the static files (ocean_static.nc, ice_static.nc) are netCDF3, which
VirtualiZarr's HDFParser can't read, and their geolon/geolat are masked over land
with a different fill value in each file, while the data files carry the full
coordinates. Everywhere else the values are identical.

    python audit/repro/04_static_files.py
"""

import h5py
import numpy as np
import s3fs
from obspec_utils.registry import ObjectStoreRegistry
from obstore.store import from_url
from scipy.io import netcdf_file
from virtualizarr import open_virtual_dataset
from virtualizarr.parsers import HDFParser

B = "s3://noaa-oar-cefi-regional-mom6-pds"
D = "northeast_pacific/full_domain/hindcast/monthly/raw/r20260701"
fs = s3fs.S3FileSystem(anon=True)
registry = ObjectStoreRegistry({B: from_url(B, region="us-east-1", skip_signature=True)})

with fs.open(f"{B}/{D}/ALB.nep.full.hcast.monthly.raw.r20260701.199301-202512.nc", "rb") as f, h5py.File(f) as h:
    data_geolon = h["geolon"][...].astype("f8")

for name in ("ocean_static.nc", "ice_static.nc"):
    url = f"{B}/{D}/{name}"
    with fs.open(url, "rb") as f:
        magic = f.read(4)
        f.seek(0)
        nc = netcdf_file(f, "r", mmap=False)
        g = np.array(nc.variables["geolon"].data, dtype="f8")
        nc.close()
    print(f"{D}/{name}")
    print(f"   first bytes {magic!r} (netCDF3: CDF\\x01 classic, CDF\\x02 64-bit offset; netCDF4 starts \\x89HDF)")
    try:
        open_virtual_dataset(url=url, parser=HDFParser(), registry=registry)
        print("   HDFParser: opened (unexpected)")
    except Exception as e:
        print(f"   HDFParser fails: {type(e).__name__}: {e}")
    fill = np.abs(g) > 1e10
    same = np.array_equal(g[~fill], data_geolon[~fill])
    print(f"   geolon: {fill.sum():,} of {g.size:,} points are fill value {np.unique(g[fill])[:1]}; "
          f"other points identical to the data files' geolon: {same}")
