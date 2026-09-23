#!/usr/bin/env python
"""Repro: CEFI's Kerchunk JSONs are empty, misnamed, or point at other directories or regions.

Each case prints the JSON object, what it references, and the NetCDF it should
correspond to. Anonymous S3 access; no credentials needed.

    python audit/repro/01_kerchunk_json_problems.py
"""

import json

import s3fs

fs = s3fs.S3FileSystem(anon=True)
B = "noaa-oar-cefi-regional-mom6-pds"
NEP = f"{B}/northeast_pacific/full_domain/hindcast"


def refs_target(key: str) -> set[str]:
    d = json.loads(fs.cat(key))
    return {v[0] for v in d["refs"].values() if isinstance(v, list)}


print("1. Empty (0-byte) JSON beside a valid NetCDF")
k = f"{NEP}/daily/raw/r20250912/o2.nep.full.hcast.daily.raw.r20250912.200801-200812.json"
print(f"   {k.rsplit('/', 1)[1]}: {fs.info(k)['size']} bytes")
print(f"   matching .nc exists: {fs.exists(k[:-5] + '.nc')}")

print("\n2. JSON named with the first character of the variable dropped")
k = f"{NEP}/daily/raw/r20250912/hlos.nep.full.hcast.daily.raw.r20250912.199301-199312.json"
print(f"   {k.rsplit('/', 1)[1]} references {[t.rsplit('/', 1)[1] for t in refs_target(k)]}")
print(f"   expected name chlos...json exists: {fs.exists(k.replace('/hlos.', '/chlos.'))}")

print("\n3. JSON named with the last character dropped")
k = f"{NEP}/monthly/raw/r20250912/ocean_stati.json"
print(f"   {k.rsplit('/', 1)[1]} references {[t.split(B + '/')[1] for t in refs_target(k)]}")

print("\n4. JSON in one release directory referencing a NetCDF in another")
k = f"{NEP}/daily/raw/r20251001/dissic.nep.full.hcast.daily.raw.r20250912.199301-199312.json"
for t in refs_target(k):
    print(f"   json dir: .../daily/raw/r20251001/  ->  references .../{'/'.join(t.split('/')[-4:])}")
k = f"{NEP}/daily/raw/r20250818/ocean_static.json"
for t in refs_target(k):
    print(f"   json dir: .../daily/raw/r20250818/  ->  references .../{'/'.join(t.split('/')[-4:])}")

print("\n4b. Static-file JSON referencing another region's static file (wrong grid)")
for k in (f"{NEP}/daily/raw/r20260701/ocean_stati.json",
          f"{B}/northwest_atlantic/full_domain/hindcast/monthly/raw/r20250715/ocean_static.json"):
    short = lambda u: u.replace("s3://", "").replace(B + "/", "").replace("/full_domain", "")
    for t in refs_target(k):
        print(f"   {short(k)}\n      -> {short(t)}")

print("\n5. Reference URLs written with and without the s3:// scheme")
for k in (
    f"{NEP}/monthly/raw/r20260701/BSNK.nep.full.hcast.monthly.raw.r20260701.199301-202512.json",
    f"{NEP}/monthly/raw/r20250912/ocean_stati.json",
):
    print(f"   {k.rsplit('/', 1)[1]}: {sorted(refs_target(k))[0][:40]}...")

print("\n6. NetCDF that no JSON references")
k = f"{NEP}/daily/raw/r20251001/btm_co3_ion.nep.full.hcast.daily.raw.r20250912.199301-202506.nc"
sib = k[:-3] + ".json"
print(f"   .../r20251001/{k.rsplit('/', 1)[1]} exists: {fs.exists(k)}")
print(f"   its sibling json references: {['/'.join(t.split('/')[-2:]) for t in refs_target(sib)]}  (the r20250912 copy)")
k = (f"{B}/northwest_atlantic/full_domain/multi_decadal_outlook/yearly/raw/r20260331/"
     "MLD_003.nwa.full.multi_decade.yearly.raw.r20260331.SSP370.1970-2100.nc")
sib = k[:-3] + ".json"
print(f"   {k.rsplit('/', 1)[1]} exists: {fs.exists(k)}; sibling json: "
      f"{fs.info(sib)['size'] if fs.exists(sib) else 'absent'} bytes")
