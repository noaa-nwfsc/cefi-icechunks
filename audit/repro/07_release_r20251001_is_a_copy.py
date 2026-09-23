#!/usr/bin/env python
"""Repro: NEP daily raw r20251001 holds files named r20250912 that are byte-identical
(same ETag) to the r20250912 directory. It lacks chlos and phycos entirely, and
2022 for seven more variables.

    python audit/repro/07_release_r20251001_is_a_copy.py
"""

import s3fs

P = "noaa-oar-cefi-regional-mom6-pds/northeast_pacific/full_domain/hindcast/daily/raw"
fs = s3fs.S3FileSystem(anon=True)
a = {k.rsplit("/", 1)[1]: v for k, v in fs.find(f"{P}/r20251001", detail=True).items() if k.endswith(".nc")}
b = {k.rsplit("/", 1)[1]: v for k, v in fs.find(f"{P}/r20250912", detail=True).items() if k.endswith(".nc")}
same = [n for n in a if n in b and a[n]["ETag"] == b[n]["ETag"]]
data = [n for n in a if ".nep." in n]
print(f"r20251001: {len(a)} .nc; data files named r20250912: {sum('r20250912' in n for n in data)} of {len(data)}")
print(f"identical ETag to r20250912 copy: {len(same)} of {len(a)}")
missing = sorted(set(b) - set(a))
gone = sorted({n.split(".")[0] for n in missing} - {n.split(".")[0] for n in a})
partial = sorted(n for n in missing if n.split(".")[0] not in gone)
print(f"in r20250912 but not r20251001: {len(missing)} files")
print(f"   variables absent entirely: {gone}")
print(f"   single years absent: {[(n.split('.')[0], n.split('.')[-2][:4]) for n in partial]}")
