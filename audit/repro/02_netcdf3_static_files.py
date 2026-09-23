#!/usr/bin/env python
"""Repro: the ocean_static / ice_static files are netCDF3, which VirtualiZarr's HDFParser can't read.

    python audit/repro/02_netcdf3_static_files.py
"""

import s3fs
from obspec_utils.registry import ObjectStoreRegistry
from obstore.store import from_url
from virtualizarr import open_virtual_dataset
from virtualizarr.parsers import HDFParser

B = "s3://noaa-oar-cefi-regional-mom6-pds"
KEY = "northeast_pacific/full_domain/hindcast/daily/raw/r20260701/ocean_static.nc"

fs = s3fs.S3FileSystem(anon=True)
with fs.open(f"{B}/{KEY}", "rb") as f:
    print(f"{KEY}\n  first bytes: {f.read(4)!r}  (netCDF3: CDF\\x01 classic, CDF\\x02 64-bit offset; netCDF4/HDF5 starts \\x89HDF)")

registry = ObjectStoreRegistry({B: from_url(B, region="us-east-1", skip_signature=True)})
try:
    open_virtual_dataset(url=f"{B}/{KEY}", parser=HDFParser(), registry=registry)
    print("  opened (unexpected)")
except Exception as e:
    print(f"  HDFParser fails: {type(e).__name__}: {e}")
