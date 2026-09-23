#!/usr/bin/env python
"""Repro: per-year daily files use a 100-step time chunk, which doesn't divide 365/366,
so VirtualiZarr can't concatenate consecutive years on a regular chunk grid.

Uses the newest NEP daily regrid release (r20260701), where the time axis itself is clean.

    python audit/repro/02_per_year_time_chunks.py
"""

import warnings

import xarray as xr
from obspec_utils.registry import ObjectStoreRegistry
from obstore.store import from_url
from virtualizarr import open_virtual_dataset
from virtualizarr.parsers import HDFParser

B = "s3://noaa-oar-cefi-regional-mom6-pds"
D = f"{B}/northeast_pacific/full_domain/hindcast/daily/regrid/r20260701"
URLS = [f"{D}/dissic.nep.full.hcast.daily.regrid.r20260701.{y}01-{y}12.nc" for y in (1993, 1994)]

registry = ObjectStoreRegistry({B: from_url(B, region="us-east-1", skip_signature=True)})
vds = []
for u in URLS:
    ds = open_virtual_dataset(url=u, parser=HDFParser(), registry=registry,
                              loadable_variables=["time", "lat", "lon", "z_l"])
    print(f"{u.rsplit('/', 1)[1]}: dissic shape {ds.dissic.shape}, chunks {ds.dissic.data.metadata.chunk_grid.chunk_shape}")
    vds.append(ds[["dissic"]])

try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        out = xr.concat(vds, dim="time", coords="minimal", compat="override")
    print("concatenated (unexpected):", out.dissic.shape)
except Exception as e:
    print(f"\nxr.concat along time fails: {type(e).__name__}: {e}")
