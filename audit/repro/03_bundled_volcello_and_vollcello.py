#!/usr/bin/env python
"""Repro: (a) a full 4-D copy of volcello is bundled inside other variables' raw files,
so a naive merge of all files in a release sees many volcello arrays; (b) NEP daily
raw and regrid carry both `volcello` and a typo'd duplicate series `vollcello`, and the
4-D daily files bundle `vollcello` and name it in external_variables.

    python audit/repro/03_bundled_volcello_and_vollcello.py
"""

import h5py
import s3fs

fs = s3fs.S3FileSystem(anon=True)
B = "noaa-oar-cefi-regional-mom6-pds"
P = f"{B}/northeast_pacific/full_domain/hindcast"

for key in (f"{P}/monthly/raw/r20260701/volcello.nep.full.hcast.monthly.raw.r20260701.199301-202512.nc",
            f"{P}/monthly/raw/r20260701/thetao.nep.full.hcast.monthly.raw.r20260701.199301-202512.nc",
            f"{P}/monthly/raw/r20260701/so.nep.full.hcast.monthly.raw.r20260701.199301-202512.nc",
            f"{B}/pacific_islands/full_domain/hindcast/monthly/raw/r20260427/"
            "calc.pci.full.hcast.monthly.raw.r20260427.199301-202512.nc"):
    with fs.open(key, "rb") as f, h5py.File(f) as h:
        print(f"{key.rsplit('/', 1)[1]}: volcello {h['volcello'].shape if 'volcello' in h else 'absent'}; "
              f"file {fs.info(key)['size'] / 1e9:.1f} GB")

d = f"{P}/daily/raw/r20260701"
names = [k.rsplit("/", 1)[1] for k in fs.ls(d)]
print(f"\ndaily/raw/r20260701: {sum(n.startswith('volcello.') and n.endswith('.nc') for n in names)} volcello files, "
      f"{sum(n.startswith('vollcello.') and n.endswith('.nc') for n in names)} vollcello files")
with fs.open(f"{d}/dissic.nep.full.hcast.daily.raw.r20260701.199301-199312.nc", "rb") as f, h5py.File(f) as h:
    print(f"dissic 1993: external_variables = {h.attrs.get('external_variables')!r}; "
          f"bundled: {[v for v in ('volcello', 'vollcello') if v in h]}")
