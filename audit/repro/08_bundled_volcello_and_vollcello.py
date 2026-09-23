#!/usr/bin/env python
"""Repro: (a) a full 4-D copy of volcello is bundled inside other variables' raw files,
so a naive merge of all files sees several volcello arrays (in r20250912 monthly raw
some are 390 steps, some 396); (b) daily raw/regrid releases carry both `volcello`
and a typo'd duplicate series `vollcello`, and files reference `vollcello` in
external_variables.

    python audit/repro/08_bundled_volcello_and_vollcello.py
"""

import h5py
import s3fs

fs = s3fs.S3FileSystem(anon=True)
P = "noaa-oar-cefi-regional-mom6-pds/northeast_pacific/full_domain/hindcast"

for key in (f"{P}/monthly/raw/r20250912/volcello.nep.full.hcast.monthly.raw.r20250912.199301-202506.nc",
            f"{P}/monthly/raw/r20250912/rhoinsitu.nep.full.hcast.monthly.raw.r20250912.199301-202506.nc",
            f"{P}/monthly/raw/r20250912/thetao.nep.full.hcast.monthly.raw.r20250912.199301-202506.nc"):
    with fs.open(key, "rb") as f, h5py.File(f) as h:
        print(f"{key.rsplit('/', 1)[1]}: volcello {h['volcello'].shape if 'volcello' in h else 'absent'}")

d = f"{P}/daily/raw/r20260701"
vols = sorted(k.rsplit("/", 1)[1] for k in fs.ls(d) if k.rsplit("/", 1)[1].startswith(("volcello", "vollcello")))
print(f"\n{d.split('hindcast/')[1]}: {sum(n.startswith('volcello') for n in vols)} volcello files, "
      f"{sum(n.startswith('vollcello') for n in vols)} vollcello files")
with fs.open(f"{d}/dissic.nep.full.hcast.daily.raw.r20260701.199301-199312.nc", "rb") as f, h5py.File(f) as h:
    print(f"dissic 1993 external_variables = {h.attrs.get('external_variables')!r}; "
          f"variables: {sorted(h)}")
