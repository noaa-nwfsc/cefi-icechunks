#!/usr/bin/env python
"""Repro: CEFI's Kerchunk JSONs are empty, misnamed, or point at another region's
static file. Newest release of each NEP and NWA product; the Pacific Islands draft
products' JSON problems are in 09_pacific_islands_draft.py.

Each case prints the JSON object and what it references. Anonymous S3 access.

    python audit/repro/08_kerchunk_json_problems.py
"""

import json

import s3fs

fs = s3fs.S3FileSystem(anon=True)
B = "noaa-oar-cefi-regional-mom6-pds"
NEP = f"{B}/northeast_pacific/full_domain/hindcast"
NWA = f"{B}/northwest_atlantic/full_domain"


def short(u):
    return u.replace("s3://", "").replace(B + "/", "").replace("/full_domain", "")


def refs(key):
    return json.loads(fs.cat(key))["refs"]


def targets(key):
    return {v[0] for v in refs(key).values() if isinstance(v, list)}


print("1. Empty (0-byte) JSON beside a valid NetCDF")
k = f"{NWA}/decadal_forecast/monthly/raw/r20250925/MLD_003.nwa.full.dc_fcast.monthly.raw.r20250925.enss.i196701.json"
print(f"   {short(k)}: {fs.info(k)['size']} bytes; .nc exists: {fs.exists(k[:-5] + '.nc')}")

print("\n2. JSON named with the first character dropped")
for k in (f"{NEP}/daily/raw/r20260701/hlos.nep.full.hcast.daily.raw.r20260701.199301-202512.json",
          f"{NEP}/daily/raw/r20260701/o3.nep.full.hcast.daily.raw.r20260701.199301-199312.json"):
    print(f"   {k.rsplit('/', 1)[1]} -> {[t.rsplit('/', 1)[1] for t in targets(k)]}")

print("\n3. Static-file JSON referencing another region's static file (wrong grid)")
for k in (f"{NEP}/daily/raw/r20260701/ocean_stati.json",
          f"{NEP}/monthly/raw/r20260701/ice_stati.json",
          f"{NWA}/hindcast/monthly/raw/r20250715/ocean_static.json"):
    for t in targets(k):
        print(f"   {short(k)}\n      -> {short(t)}")

print("\n4. Reference URLs written with and without the s3:// scheme")
for k in (f"{NEP}/monthly/raw/r20260701/BSNK.nep.full.hcast.monthly.raw.r20260701.199301-202512.json",
          f"{NEP}/monthly/raw/r20260701/ice_stati.json"):
    print(f"   {k.rsplit('/', 1)[1]}: {sorted(targets(k))[0][:40]}...")

print("\n5. NetCDF with an empty JSON and no other JSON referencing it")
k = f"{NWA}/multi_decadal_outlook/yearly/raw/r20260331/MLD_003.nwa.full.multi_decade.yearly.raw.r20260331.SSP370.1970-2100.nc"
sib = k[:-3] + ".json"
print(f"   {k.rsplit('/', 1)[1]} exists: {fs.exists(k)}; sibling json: "
      f"{fs.info(sib)['size'] if fs.exists(sib) else 'absent'} bytes")
