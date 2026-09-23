#!/usr/bin/env python
"""Repro: NWA forecast coordinate problems in the newest releases.
  - seasonal forecast r20250710: init 202510 files have 9 members (member 6 missing)
  - seasonal forecast vs reforecast: dimension order (lead, member) vs (member, lead)
  - seasonal reforecast r20250413: _FillValue is 9.97e36 in some inits and NaN in others
  - lead: 'months' in seasonal forecasts, no units in reforecasts, and
    'days since <init date>' in decadal forecasts (monthly r20250925, yearly r20250819).
    The decadal numbers differ between inits (they follow the calendar), and decoded
    they become different absolute dates for every init

    python audit/repro/07_forecast_coordinates.py
"""

import collections

import h5py
import s3fs

fs = s3fs.S3FileSystem(anon=True)
N = "noaa-oar-cefi-regional-mom6-pds/northwest_atlantic/full_domain"


def show(key, var):
    with fs.open(key, "rb") as f, h5py.File(f) as h:
        dims = [d[0].name.lstrip("/") if len(d) else "?" for d in h[var].dims]
        lead = h["lead"]
        print(f"{key.rsplit('/', 1)[1]}\n   {var} dims {dims} shape {h[var].shape}; "
              f"member {h['member'][...].astype(int).tolist()}\n   lead units={lead.attrs.get('units')!r} "
              f"first values {lead[:3].tolist()}")


sf = f"{N}/seasonal_forecast/monthly/raw/r20250710"
show(f"{sf}/MLD_003.nwa.full.ss_fcast.monthly.raw.r20250710.enss.i202601.nc", "MLD_003")
show(f"{sf}/MLD_003.nwa.full.ss_fcast.monthly.raw.r20250710.enss.i202510.nc", "MLD_003")

rf = f"{N}/seasonal_reforecast/monthly/raw/r20250413"
show(f"{rf}/tos.nwa.full.ss_refcast.monthly.raw.r20250413.enss.i199401.nc", "tos")
fills = collections.Counter()
for k in sorted(k for k in fs.ls(rf) if k.rsplit("/", 1)[1].startswith("tos.") and k.endswith(".nc")):
    with fs.open(k, "rb") as f, h5py.File(f) as h:
        fills[str(h["tos"].fillvalue)] += 1
print(f"reforecast r20250413 tos fill values across {sum(fills.values())} inits: {dict(fills)}")

for rel, freq in (("r20250925", "monthly"), ("r20250819", "yearly")):
    for init in ("196501", "202001"):
        key = (f"{N}/decadal_forecast/{freq}/raw/{rel}/"
               f"tos.nwa.full.dc_fcast.{freq}.raw.{rel}.enss.i{init}.nc")
        with fs.open(key, "rb") as f, h5py.File(f) as h:
            lead = h["lead"]
            print(f"decadal {freq} {rel} init {init}: lead units={lead.attrs.get('units')!r} "
                  f"calendar={lead.attrs.get('calendar')!r} first values {lead[:3].tolist()}")
