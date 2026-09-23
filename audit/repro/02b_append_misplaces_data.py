#!/usr/bin/env python
"""Repro: appending per-year daily files one year at a time misplaces the data.

Concatenating the per-year files is refused (02a). Appending them one year at a time
with VirtualiZarr's `vz.to_icechunk(..., append_dim="time")` is not refused, but the
source time chunk (100 days) doesn't divide 365, and the append doesn't check that.
The second year's chunks are written starting at chunk slot floor(365 / 100) = 3,
index 300, instead of at index 365. So the first year's last 65 days are overwritten,
and the second year's data sits 65 days earlier than its time coordinate says.

This script builds a throwaway in-memory Icechunk store from two yearly NEP daily regrid
files (r20260701, the newest release) and compares one surface grid point with the
source NetCDFs. It reads a few 160 MB chunks.

    python audit/repro/02b_append_misplaces_data.py
"""

import warnings

import h5py
import icechunk as ic
import numpy as np
import s3fs
import xarray as xr
import zarr
from obspec_utils.registry import ObjectStoreRegistry
from obstore.store import from_url
from virtualizarr import open_virtual_dataset
from virtualizarr.parsers import HDFParser

warnings.filterwarnings("ignore")

BUCKET = "s3://noaa-oar-cefi-regional-mom6-pds"
D = "northeast_pacific/full_domain/hindcast/daily/regrid/r20260701"
YEARS = (1993, 1994)
Y, X = 300, 250  # an ocean point on the regrid grid

registry = ObjectStoreRegistry({BUCKET: from_url(BUCKET, region="us-east-1", skip_signature=True)})
config = ic.RepositoryConfig.default()
config.set_virtual_chunk_container(
    ic.VirtualChunkContainer(url_prefix=f"{BUCKET}/", store=ic.s3_store(region="us-east-1", anonymous=True))
)
repo = ic.Repository.create(
    ic.in_memory_storage(),
    config,
    authorize_virtual_chunk_access=ic.containers_credentials({f"{BUCKET}/": ic.s3_anonymous_credentials()}),
)

session = repo.writable_session("main")
for i, year in enumerate(YEARS):
    url = f"{BUCKET}/{D}/dissic.nep.full.hcast.daily.regrid.r20260701.{year}01-{year}12.nc"
    vds = open_virtual_dataset(url=url, parser=HDFParser(), registry=registry,
                               loadable_variables=["time", "lat", "lon", "z_l"])[["dissic"]]
    vds.vz.to_icechunk(session.store, **({} if i == 0 else {"append_dim": "time"}))
    print(f"{'wrote' if i == 0 else 'appended'} {year}: {vds.sizes['time']} days, "
          f"time chunk {vds.dissic.data.metadata.chunk_grid.chunk_shape[0]}")
session.commit("two years, appended")

ds = xr.open_zarr(repo.readonly_session("main").store, consolidated=False)
store = zarr.open_group(repo.readonly_session("main").store, mode="r")["dissic"]
print(f"store: dissic shape {store.shape}, chunks {store.metadata.chunk_grid.chunk_shape}")

fs = s3fs.S3FileSystem(anon=True)
src = {}
for year in YEARS:
    key = f"{BUCKET[5:]}/{D}/dissic.nep.full.hcast.daily.regrid.r20260701.{year}01-{year}12.nc"
    with fs.open(key, "rb", block_size=2**22, cache_type="blockcache") as f, h5py.File(f) as h:
        src[year] = h["dissic"][:, 0, Y, X]


def source_for(index):
    """(year, day) of the source value at a position in the concatenated series."""
    return (YEARS[0], index) if index < len(src[YEARS[0]]) else (YEARS[1], index - len(src[YEARS[0]]))


def value(year, day):
    return src[year][day] if 0 <= day < len(src[year]) else None


n0 = len(src[YEARS[0]])
start2 = (n0 // 100) * 100  # where the append actually put the second year
print(f"\n{'index':>5}  {'time coord':>10}  {'should hold':>12}  {'match':>5}  {'actually holds':>14}")
for i in (299, 300, 364, 365, 399, 400, 664, 665, 729):
    s = store[i, 0, Y, X]
    want = source_for(i)
    ok = value(*want) is not None and np.isclose(s, value(*want))
    got = (YEARS[1], i - start2) if i >= start2 else (YEARS[0], i)
    holds = f"{got[0]} day {got[1]}" if value(*got) is not None and np.isclose(s, value(*got)) else f"{s:.3g}"
    print(f"{i:>5}  {str(ds.time.values[i])[:10]:>10}  {want[0]} day {want[1]:>3}  {'yes' if ok else 'NO':>5}  {holds:>14}")
