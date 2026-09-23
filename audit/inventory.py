#!/usr/bin/env python
"""List every object in the CEFI bucket and parse path + filename into fields.

Output: audit/out/inventory.parquet, one row per object.

    python audit/inventory.py
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import s3fs

BUCKET = "noaa-oar-cefi-regional-mom6-pds"
OUT = Path(__file__).parent / "out" / "inventory.parquet"

# <var>.<reg>.full.<exp>.<freq>.<grid>.<release>.<YYYYMM>-<YYYYMM>.<ext>
HINDCAST_RE = re.compile(
    r"^(?P<var>.+?)\.(?P<reg>[a-z]+)\.full\.(?P<exp_code>[a-z_]+)\.(?P<fname_freq>[a-z]+)"
    r"\.(?P<fname_grid>raw|regrid)\.(?P<fname_release>r\d{8})"
    r"\.(?P<start>\d{6})-(?P<end>\d{6})\.(?P<ext>nc|json)$"
)
# <var>.<reg>.full.<exp>.<freq>.<grid>.<release>.enss.i<YYYYMM>.<ext>
FORECAST_RE = re.compile(
    r"^(?P<var>.+?)\.(?P<reg>[a-z]+)\.full\.(?P<exp_code>[a-z_]+)\.(?P<fname_freq>[a-z]+)"
    r"\.(?P<fname_grid>raw|regrid)\.(?P<fname_release>r\d{8})"
    r"\.(?P<ens>[a-z0-9]+)\.i(?P<init>\d{6})\.(?P<ext>nc|json)$"
)
# <var>.<reg>.full.<exp>.<freq>.<grid>.<release>.<scenario>.<YYYY>-<YYYY>.<ext>
SCENARIO_RE = re.compile(
    r"^(?P<var>.+?)\.(?P<reg>[a-z]+)\.full\.(?P<exp_code>[a-z_]+)\.(?P<fname_freq>[a-z]+)"
    r"\.(?P<fname_grid>raw|regrid)\.(?P<fname_release>r\d{8})"
    r"\.(?P<scenario>[A-Za-z0-9]+)\.(?P<start>\d{4})-(?P<end>\d{4})\.(?P<ext>nc|json)$"
)


def parse(key: str, size: int) -> dict:
    parts = key.split("/")
    row = {"key": key, "size": size, "name": parts[-1]}
    # bucket/region/full_domain/experiment/freq/grid/release/file
    if len(parts) == 8:
        row.update(
            region=parts[1],
            domain=parts[2],
            experiment=parts[3],
            freq=parts[4],
            grid=parts[5],
            release=parts[6],
        )
        row["group"] = "/".join(parts[1:7])
    for kind, rx in (("hindcast", HINDCAST_RE), ("forecast", FORECAST_RE), ("scenario", SCENARIO_RE)):
        m = rx.match(parts[-1])
        if m:
            row.update(m.groupdict(), name_pattern=kind)
            break
    else:
        row["name_pattern"] = "unparsed"
        row["ext"] = parts[-1].rsplit(".", 1)[-1] if "." in parts[-1] else ""
    return row


def main() -> None:
    fs = s3fs.S3FileSystem(anon=True)
    objs = fs.find(BUCKET, detail=True)
    df = pd.DataFrame(parse(k, v["size"]) for k, v in objs.items())
    OUT.parent.mkdir(exist_ok=True)
    df.to_parquet(OUT, index=False)
    print(f"{len(df)} objects -> {OUT}")
    print(df.groupby(["name_pattern", "ext"]).size().to_string())
    # directory fields that disagree with the filename fields
    nc = df[df.name_pattern != "unparsed"]
    for a, b in (("freq", "fname_freq"), ("grid", "fname_grid"), ("release", "fname_release")):
        bad = nc[nc[a] != nc[b]]
        print(f"{a} dir/filename mismatches: {len(bad)}")


if __name__ == "__main__":
    main()
