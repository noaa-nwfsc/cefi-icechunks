#!/usr/bin/env python
"""Repro: problems in the Pacific Islands (PCI) r20260427 products, which are still drafts.
  - PCI-2: T_adx_2d has a time axis of length 0 with no units, data [0, 539, 726], and
    zeroed xq/yh; ffedet_btm's data is empty [0, 539, 725] with zeroed xh/yh; the
    `speed` file has no `speed` variable and zeroed xh/yh.
  - PCI-3: time_bnds chunk [800, 2] (418 files) and average_DT chunk [512] (406 files)
    exceed the 396-step axis, which VirtualiZarr accepts for reading but refuses to
    concatenate.
  - PCI-5: Kerchunk JSONs that are misnamed, point at another directory, or disagree
    with the NetCDF (calc's offsets shifted by a constant; T_adx_2d's shape).

Chunk sizes (PCI-1) are in 01_chunk_sizes_and_shapes.py and the bundled volcello
(PCI-4) in 03_bundled_volcello_and_vollcello.py.

    python audit/repro/09_pacific_islands_draft.py
"""

import json

import h5py
import s3fs

fs = s3fs.S3FileSystem(anon=True)
B = "noaa-oar-cefi-regional-mom6-pds"
PCI = f"{B}/pacific_islands/full_domain/hindcast"
D = f"{PCI}/monthly/raw/r20260427"


def short(u):
    return u.replace("s3://", "").replace(B + "/", "").replace("/full_domain", "")


def refs(key):
    return json.loads(fs.cat(key))["refs"]


def summarize(var):
    key = f"{D}/{var}.pci.full.hcast.monthly.raw.r20260427.199301-202512.nc"
    with fs.open(key, "rb") as f, h5py.File(f) as h:
        print(f"{var}: variables {sorted(h)}")
        for c in ("time", "xh", "yh", "xq"):
            if c in h:
                v = h[c][...]
                units = h[c].attrs.get("units")
                print(f"   {c}: n={v.size} min={v.min() if v.size else '-'} "
                      f"max={v.max() if v.size else '-'} units={units!r}")
        if var in h:
            print(f"   {var}: shape {h[var].shape} chunks {h[var].chunks}")
        for c in ("time_bnds", "average_DT"):
            if c in h:
                print(f"   {c}: shape {h[c].shape} chunks {h[c].chunks}")
    return key


print("PCI-2 / PCI-3: empty or broken files, oversized chunks")
key = summarize("T_adx_2d")
summarize("speed")
summarize("ffedet_btm")
summarize("Heat_PmE")

print("\nPCI-5: Kerchunk JSONs")
k = key[:-3] + ".json"
print(f"   {k.rsplit('/', 1)[1]}: JSON shape {json.loads(refs(k)['T_adx_2d/.zarray'])['shape']}; "
      "the NetCDF's T_adx_2d is [0, 539, 726]")

k = f"{D}/alc.pci.full.hcast.monthly.raw.r20260427.199301-202512.json"
r = refs(k)
first = r["calc/0.0.0.0"]
with fs.open(f"{D}/calc.pci.full.hcast.monthly.raw.r20260427.199301-202512.nc", "rb") as f, h5py.File(f) as h:
    info = h["calc"].id.get_chunk_info_by_coord((0, 0, 0, 0))
print(f"   {k.rsplit('/', 1)[1]} (misnamed; for calc...nc): chunk 0.0.0.0 at offset {first[1]}, length {first[2]}")
print(f"   the NetCDF's own chunk index: offset {info.byte_offset}, length {info.size} "
      f"(shift {info.byte_offset - first[1]:+d} bytes; the same shift applies to every chunk)")
print(f"   volcello, bundled in the NetCDF, present in the json: {'volcello/.zarray' in r}")

for k in (f"{D}/ocean_stati.json", f"{PCI}/daily/raw/r20260427/ocean_stati.json"):
    targets = {v[0] for v in refs(k).values() if isinstance(v, list)}
    print(f"   {short(k)} (misnamed) -> {[short(t) for t in targets]}")
