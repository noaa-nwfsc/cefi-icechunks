#!/usr/bin/env python
"""Repro: NWA seasonal forecast/reforecast ensemble problems.
  - r20250413 forecast: member coordinate out of order (e.g. 1,2,3,4,5,7,6,8,9,10)
  - r20250710 forecast: init 202510 files have 9 members (member 6 missing)
  - r20250413 reforecast: _FillValue is NaN in some inits and 9.97e36 in others
  - r20250212 reforecast: init months step irregularly (2, 3 and 4 months apart)
  - lead is plain integers in seasonal files but 'days since <init>' in decadal files

    python audit/repro/11_seasonal_forecast_members.py
"""

import collections

import h5py
import s3fs

fs = s3fs.S3FileSystem(anon=True)
N = "noaa-oar-cefi-regional-mom6-pds/northwest_atlantic/full_domain"


for name in ("sos.nwa.full.ss_fcast.monthly.raw.r20250413.enss.i202507.nc",
             "sob.nwa.full.ss_fcast.monthly.raw.r20250413.enss.i202507.nc"):
    with fs.open(f"{N}/seasonal_forecast/monthly/raw/r20250413/{name}", "rb") as f, h5py.File(f) as h:
        print(f"{name}: member = {h['member'][...].astype(int).tolist()}")

for init in ("202601", "202510"):
    name = f"MLD_003.nwa.full.ss_fcast.monthly.raw.r20250710.enss.i{init}.nc"
    with fs.open(f"{N}/seasonal_forecast/monthly/raw/r20250710/{name}", "rb") as f, h5py.File(f) as h:
        print(f"{name}: member = {h['member'][...].astype(int).tolist()}, MLD_003 {h['MLD_003'].shape}")

d = f"{N}/seasonal_reforecast/monthly/raw/r20250413"
fills = collections.Counter()
for k in sorted(k for k in fs.ls(d) if k.rsplit("/", 1)[1].startswith("tos.") and k.endswith(".nc"))[:40]:
    with fs.open(k, "rb") as f, h5py.File(f) as h:
        fills[str(h["tos"].fillvalue)] += 1
print(f"reforecast r20250413 tos fill values over 40 inits: {dict(fills)}")

d = f"{N}/seasonal_reforecast/monthly/raw/r20250212"
inits = sorted({k.rsplit(".i", 1)[1][:6] for k in fs.ls(d) if k.endswith(".nc") and ".enss.i" in k})
months = [int(i[:4]) * 12 + int(i[4:]) for i in inits]
print(f"reforecast r20250212 init steps (months): {dict(collections.Counter(b - a for a, b in zip(months, months[1:])))}; "
      f"first inits {inits[:6]}")

for key in (f"{N}/seasonal_forecast/monthly/raw/r20250710/MLD_003.nwa.full.ss_fcast.monthly.raw.r20250710.enss.i202601.nc",
            f"{N}/decadal_forecast/monthly/raw/r20250925/MLD_003.nwa.full.dc_fcast.monthly.raw.r20250925.enss.i196501.nc"):
    with fs.open(key, "rb") as f, h5py.File(f) as h:
        print(f"{key.rsplit('/', 1)[1]}: lead units={h['lead'].attrs.get('units')!r} "
              f"first values {h['lead'][:3].tolist()}")
