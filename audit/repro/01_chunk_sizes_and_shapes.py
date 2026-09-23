#!/usr/bin/env python
"""Repro: chunking has no standard, and chunk sizes are poorly suited to cloud reads.

For one example file per case, prints the main variable's chunk shape, its
uncompressed size, and the compressed size of its chunks, as fetched per read.
Compressed sizes come from the chunk index, via the Kerchunk JSON beside each
file (these JSONs were checked chunk by chunk against VirtualiZarr's manifest).

    python audit/repro/01_chunk_sizes_and_shapes.py
"""

import json

import h5py
import numpy as np
import s3fs

fs = s3fs.S3FileSystem(anon=True)
B = "noaa-oar-cefi-regional-mom6-pds"
CASES = {
    "PCI monthly raw 2-D": "pacific_islands/full_domain/hindcast/monthly/raw/r20260427/Heat_PmE.pci.full.hcast.monthly.raw.r20260427.199301-202512",
    "PCI monthly raw 4-D": "pacific_islands/full_domain/hindcast/monthly/raw/r20260427/rsdo.pci.full.hcast.monthly.raw.r20260427.199301-202512",
    "PCI daily raw 2-D": "pacific_islands/full_domain/hindcast/daily/raw/r20260427/btm_o2.pci.full.hcast.daily.raw.r20260427.199301-202512",
    "PCI monthly regrid 2-D": "pacific_islands/full_domain/hindcast/monthly/regrid/r20260427/Heat_PmE.pci.full.hcast.monthly.regrid.r20260427.199301-202512",
    "NEP monthly raw 2-D": "northeast_pacific/full_domain/hindcast/monthly/raw/r20260701/tos.nep.full.hcast.monthly.raw.r20260701.199301-202512",
    "NEP monthly raw 3-D": "northeast_pacific/full_domain/hindcast/monthly/raw/r20260701/thetao.nep.full.hcast.monthly.raw.r20260701.199301-202512",
    "NEP daily raw 2-D": "northeast_pacific/full_domain/hindcast/daily/raw/r20260701/tos.nep.full.hcast.daily.raw.r20260701.199301-202512",
    "NWA monthly regrid 3-D": "northwest_atlantic/full_domain/hindcast/monthly/regrid/r20250715/thetao.nwa.full.hcast.monthly.regrid.r20250715.199301-202312",
}

print(f"{'case':24s} {'chunk shape':22s} {'uncompressed':>12s} {'compressed median (10-90%)':>30s} {'chunks':>8s}")
for label, stem in CASES.items():
    var = stem.rsplit("/", 1)[1].split(".")[0]
    key = f"{B}/{stem}.nc"
    if not fs.exists(key):
        print(f"{label:24s} (example file not found: {stem.rsplit('/', 1)[1]}.nc)")
        continue
    with fs.open(key, "rb") as f, h5py.File(f) as h:
        chunks, dtype = h[var].chunks, h[var].dtype
    raw_mb = np.prod(chunks) * dtype.itemsize / 1e6
    try:
        refs = json.loads(fs.cat(f"{B}/{stem}.json"))["refs"]
        lengths = np.array([v[2] for k, v in refs.items() if k.startswith(var + "/") and isinstance(v, list)])
        comp = (f"{np.median(lengths) / 1e3:,.0f} KB ({np.percentile(lengths, 10) / 1e3:,.0f}-"
                f"{np.percentile(lengths, 90) / 1e3:,.0f} KB)")
        n = f"{len(lengths):,}"
    except Exception:
        comp, n = "(no usable JSON)", "-"
    print(f"{label:24s} {str(list(chunks)):22s} {raw_mb:9.1f} MB {comp:>30s} {n:>8s}")
