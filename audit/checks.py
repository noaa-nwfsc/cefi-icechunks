#!/usr/bin/env python
"""Run every audit check over the scanned tables and write findings.

Inputs (audit/out/): inventory.parquet, kerchunk.jsonl, files.parquet,
vars.parquet, axes.parquet.  Outputs: findings.csv (one row per problem) and
time_axes.csv (per group x variable axis signature, the merge-blocker table).

Each finding has a `category`:
    single-group  stops the variable from sharing one Icechunk group with the rest
    concat        stops a variable's files from being concatenated along time/init
    chunking      chunk sizes or shapes poorly suited to cloud reads, or inconsistent
    kerchunk      a problem in CEFI's Kerchunk JSONs
    file          a file that is unreadable, misnamed, or in an unexpected format
    hygiene       inconsistent metadata that won't block a build but should be fixed

    python audit/checks.py
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

import cftime
import numpy as np
import pandas as pd

OUT = Path(__file__).parent / "out"
FINDINGS: list[dict] = []

# variables expected alongside the primary one; anything else in a file is "bundled"
AUX_VARS = {
    "average_T1", "average_T2", "average_DT", "time_bnds", "time_bounds", "nv", "bnds",
    "geolon", "geolat", "geolon_c", "geolat_c", "geolon_u", "geolat_u", "geolon_v", "geolat_v",
    "lon", "lat", "lon_bnds", "lat_bnds", "crs", "ncrs", "init", "month", "lead", "member",
}
COORD_1D = ("xh", "yh", "xq", "yq", "ih", "jh", "iq", "jq", "lat", "lon", "z_l", "z_i", "zl", "zi", "member")
UNIT_DAYS = {"days": 1.0, "day": 1.0, "hours": 1 / 24, "hour": 1 / 24, "seconds": 1 / 86400, "minutes": 1 / 1440}
STEP_DAYS = {"daily": (1.0, 1.0), "monthly": (28.0, 31.0), "yearly": (365.0, 366.0)}


def add(category, check, group=None, var=None, files=(), detail="", n_files=None):
    files = list(files)
    FINDINGS.append(
        {
            "category": category,
            "check": check,
            "group": group,
            "var": var,
            "n_files": n_files if n_files is not None else len(files),
            "files": " ".join(os.path.basename(f) for f in files[:5]) + (" ..." if len(files) > 5 else ""),
            "detail": detail,
        }
    )


def unit_scale(units: str | None) -> float | None:
    if not isinstance(units, str) or " since " not in units:
        return None
    return UNIT_DAYS.get(units.split(" since ")[0].strip().lower())


def decode(vals, units, calendar):
    try:
        return cftime.num2date(np.asarray(vals, dtype="float64"), units, calendar or "standard")
    except Exception:
        return None


def ym(d) -> str:
    return f"{d.year:04d}{d.month:02d}"


# ---------------------------------------------------------------- inventory + kerchunk
def check_inventory(inv: pd.DataFrame) -> None:
    for name, g in inv[inv.name_pattern == "unparsed"].groupby("name"):
        if name.endswith(".html"):
            continue
        add("file", "nonstandard-filename", None, None, g.key, f"{name} in {g.group.nunique()} release dirs")

    mm = inv[(inv.name_pattern != "unparsed") & (inv.release != inv.fname_release)]
    for grp, g in mm.groupby("group"):
        add("file", "release-dir-vs-filename", grp, None, g.key,
            f"directory release {g.release.iloc[0]} but filenames say {sorted(g.fname_release.unique())}")

    # typo'd duplicates: one name is the other with a letter doubled (vollcello/volcello).
    # A plain one-edit rule flags real MOM6 pairs like so/sos and uo/umo.
    for grp, g in inv[inv.ext == "nc"].dropna(subset=["var"]).groupby("group"):
        names = sorted(g["var"].unique())
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                if _doubled_letter(a, b):
                    add("file", "near-duplicate-variable-name", grp, f"{a}|{b}",
                        g[g["var"].isin([a, b])].key, f"'{a}' and '{b}' both present")

    # same series with overlapping periods in one release dir
    hc = inv[(inv.ext == "nc") & (inv.name_pattern == "hindcast")]
    for (grp, var), g in hc.groupby(["group", "var"]):
        spans = sorted(zip(g.start, g.end, g.key))
        for (s1, e1, k1), (s2, e2, k2) in zip(spans, spans[1:]):
            if s2 <= e1:
                add("concat", "overlapping-period-files", grp, var, [k1, k2], f"{s1}-{e1} overlaps {s2}-{e2}")

    # whole release dirs that repeat another release byte-for-byte (by name+size)
    nc = inv[inv.ext == "nc"].copy()
    nc["series"] = nc.group.str.rsplit("/", n=1).str[0]
    for series, g in nc.groupby("series"):
        rels = {r: set(zip(x.name, x["size"])) for r, x in g.groupby("release")}
        for r1 in rels:
            for r2 in rels:
                if r1 < r2:
                    common = rels[r1] & rels[r2]
                    if len(common) > 0.5 * min(len(rels[r1]), len(rels[r2])):
                        add("file", "release-duplicates-another", f"{series}/{r2}", None, [],
                            f"{len(common)} of {len(rels[r2])} files in {r2} have the same name and size as in {r1}",
                            n_files=len(common))


def _doubled_letter(a: str, b: str) -> bool:
    if len(a) > len(b):
        a, b = b, a
    if len(b) != len(a) + 1:
        return False
    return any(b[i] == b[i - 1] and b[:i] + b[i + 1:] == a for i in range(1, len(b)))


def check_kerchunk(inv: pd.DataFrame) -> None:
    ncs = set(inv[inv.ext == "nc"].key)
    referenced = set()
    cats = defaultdict(list)
    for line in (OUT / "kerchunk.jsonl").open():
        r = json.loads(line)
        k = r["key"]
        if "urls" not in r:
            cats["empty-or-unparseable-json", r.get("error")].append(k)
            continue
        us = [u.replace("s3://", "") for u in r["urls"]]
        referenced.update(us)
        if any("://" not in u for u in r["urls"]):
            cats["json-url-missing-s3-scheme", None].append(k)
        sib = k[:-5] + ".nc"
        if len(us) > 1:
            cats["json-references-many-files", f"{len(us)} files"].append(k)
        elif us[0] == sib:
            pass
        elif us[0] not in ncs:
            cats["json-points-to-missing-nc", None].append(k)
        elif us[0].split("/")[1:4] != k.split("/")[1:4]:
            # a different region or experiment: silently the wrong grid
            cats["json-points-to-other-region-or-experiment", "/".join(us[0].split("/")[1:7])].append(k)
        elif os.path.dirname(us[0]) != os.path.dirname(k):
            cats["json-points-to-other-directory", "/".join(us[0].split("/")[4:7])].append(k)
        else:
            a, b = os.path.basename(k)[:-5], os.path.basename(us[0])[:-3]
            how = "first character dropped" if b[1:] == a else "last character dropped" if b[:-1] == a else "other"
            cats["json-misnamed", how].append(k)
    for (check, why), keys in cats.items():
        for grp, ks in pd.Series(keys).groupby(pd.Series(keys).map(lambda k: "/".join(k.split("/")[1:7]))):
            add("kerchunk", check, grp, None, ks, why or "")
    unref = pd.Series(sorted(ncs - referenced))
    for grp, ks in unref.groupby(unref.map(lambda k: "/".join(k.split("/")[1:7]))):
        add("kerchunk", "nc-not-referenced-by-any-json", grp, None, ks, "")



def check_smoke() -> None:
    """VirtualiZarr parse failures, and Kerchunk refs that disagree with its manifest."""
    path = OUT / "smoke.jsonl"
    if not path.exists():
        return
    fails = defaultdict(list)
    for line in path.open():
        r = json.loads(line)
        grp = "/".join(r["key"].split("/")[1:7])
        if r.get("vz_error"):
            fails[grp, r["vz_error"].split("(")[0].strip()].append(r["key"])
        for name, d in (r.get("kerchunk_diff") or {}).items():
            if isinstance(d, dict) and d["n_vz"] == 1 and d["n_extra_in_json"] == 1 and d["examples"] \
                    and d["examples"][0][0] == "" and not d["meta"]:
                continue  # scalar chunk key "" vs "0" (runs before the smoke script normalized it)
            detail = d if isinstance(d, str) else (
                f"{d['n_bad']} of {d['n_vz']} chunk refs differ from VirtualiZarr's manifest; "
                f"{d['n_extra_in_json']} extra refs in json; {'; '.join(d['meta'])}")
            add("kerchunk", "json-disagrees-with-netcdf", grp, name, [r["key"]], detail)
    for (grp, err), keys in fails.items():
        add("file", "virtualizarr-cannot-parse", grp, None, keys, err)


# ---------------------------------------------------------------- per file
def check_files(files: pd.DataFrame, vars_: pd.DataFrame) -> pd.DataFrame:
    for (grp, err), g in files[files.error.notna()].groupby(["group", "error"]):
        add("file", "unreadable-file", grp, None, g.key, err)
    for grp, g in files[files.signature == "netcdf3"].groupby("group"):
        add("file", "netcdf3-format", grp, None, g.key,
            "netCDF3 classic: VirtualiZarr's HDFParser can't read it (needs the netCDF3 parser or conversion)")
    for grp, g in files[files.groups.fillna("[]") != "[]"].groupby("group"):
        add("hygiene", "hdf5-subgroups", grp, None, g.key, str(g.groups.iloc[0]))

    prim = vars_.merge(files[["key", "var"]], on="key")
    prim = prim[prim.vname == prim["var"]]
    missing = files[(files.signature.notna()) & files["var"].notna() & ~files.key.isin(prim.key)]
    for grp, g in missing.groupby("group"):
        add("file", "filename-variable-not-in-file", grp, None, g.key,
            f"e.g. {g['var'].iloc[0]}: the variable named in the filename isn't in the file")
    empty = prim[prim["shape"].map(lambda s: 0 in json.loads(s))].merge(files[["key", "group"]], on="key")
    for grp, g in empty.groupby("group"):
        add("file", "empty-data-variable", grp, None, g.key,
            "; ".join(f"{r.vname} shape {r.shape}" for r in g.head(5).itertuples()))
    for (grp, err), g in vars_[vars_.error.notna()].merge(files[["key", "group"]]).groupby(["group", "error"]):
        add("file", "variable-metadata-unreadable", grp, None, g.key, err)
    return prim


# ---------------------------------------------------------------- time axes
def time_table(files: pd.DataFrame, axes: pd.DataFrame) -> pd.DataFrame:
    t = axes[axes.vname == "time"].merge(
        files[["key", "group", "region", "experiment", "freq", "grid", "release", "var", "start", "end", "scenario", "name_pattern"]],
        on="key",
    )
    return t


def check_time_per_file(t: pd.DataFrame) -> None:
    rows = defaultdict(list)
    for r in t.itertuples():
        vals = np.asarray(r.values, dtype="float64")
        scale = unit_scale(r.units)
        if scale is None:
            rows["time-units-not-cf", r.group, r.var, f"units={r.units!r}"].append(r.key)
            continue
        d = np.diff(vals) * scale
        if len(vals) != len(np.unique(vals)):
            n = len(vals) - len(np.unique(vals))
            rows["duplicate-time-stamps", r.group, r.var, f"{n} duplicated of {len(vals)}"].append(r.key)
        if (d <= 0).any():
            rows["time-not-monotonic", r.group, r.var, f"{int((d <= 0).sum())} backward/equal steps"].append(r.key)
        lo, hi = STEP_DAYS.get(r.freq, (None, None))
        if lo is not None and len(d):
            bad = d[(d > 0) & ((d < lo - 0.51) | (d > hi + 0.51))]
            if len(bad):
                rows["irregular-time-step", r.group, r.var,
                     f"{len(bad)} steps outside {lo}-{hi} days, e.g. {sorted(set(np.round(bad, 2)))[:4]}"].append(r.key)
        if r.name_pattern == "hindcast" and len(vals):
            dates = decode(vals[[0, -1]], r.units, r.calendar)
            if dates is None:
                rows["time-undecodable", r.group, r.var, f"{r.units} / {r.calendar}"].append(r.key)
            elif (ym(dates[0]), ym(dates[1])) != (r.start, r.end):
                rows["filename-period-vs-time-coord", r.group, r.var,
                     f"filename {r.start}-{r.end}, time coord {ym(dates[0])}-{ym(dates[1])}"].append(r.key)
    for (check, grp, var, detail), keys in rows.items():
        cat = "single-group" if check in ("duplicate-time-stamps", "time-not-monotonic") else "concat" if check in (
            "irregular-time-step",) else "hygiene"
        add(cat, check, grp, var, keys, detail)

    t = t[t.name_pattern != "forecast"].assign(units=t.units.str.replace(" 00:00:00", "", regex=False))
    for grp, g in t.groupby("group"):
        combos = g.groupby(["units", "calendar"], dropna=False).size()
        if len(combos) > 1:
            add("hygiene", "time-units-or-calendar-vary", grp, None, [],
                "; ".join(f"{u} / {c}: {n} files" for (u, c), n in combos.items()), n_files=len(g))


def axis_signatures(t: pd.DataFrame, files: pd.DataFrame, prim: pd.DataFrame) -> pd.DataFrame:
    """One row per (group, var): the concatenated time axis and the chunking that goes with it."""
    rows = []
    hc = t[t.name_pattern.isin(["hindcast", "scenario"])]
    pr = prim.set_index("key")
    for (grp, var, scen), g in hc.groupby(["group", "var", hc.scenario.fillna("")]):
        g = g.sort_values(["start", "key"])
        scale = unit_scale(g.units.iloc[0]) or 1.0
        # express every file's axis in days since 1900 so different reference dates compare
        parts = []
        for r in g.itertuples():
            ref = decode([0.0], r.units, r.calendar)
            base = cftime.date2num(ref[0], "days since 1900-01-01", r.calendar or "standard") if ref is not None else 0
            parts.append(np.asarray(r.values) * (unit_scale(r.units) or 1.0) + base)
        allv = np.concatenate(parts)
        shapes = [json.loads(pr.loc[k, "shape"]) for k in g.key if k in pr.index]
        chunks = [json.loads(pr.loc[k, "chunks"]) if pr.loc[k, "chunks"] else None for k in g.key if k in pr.index]
        tchunks = sorted({c[0] for c in chunks if c})
        file_lens = [s[0] for s in shapes if s]
        dates = decode(allv[[0, -1]], "days since 1900-01-01", g.calendar.iloc[0]) if len(allv) else None
        rows.append(
            {
                "group": grp,
                "var": var if not scen else f"{var}.{scen}",
                "n_files": len(g),
                "ntime": len(allv),
                "n_unique": len(np.unique(allv)),
                "first": str(dates[0])[:10] if dates is not None else None,
                "last": str(dates[1])[:10] if dates is not None else None,
                "axis_sha1": hashlib.sha1(np.round(allv, 4).tobytes()).hexdigest()[:10],
                "time_chunks": json.dumps(tchunks),
                "file_ntime": json.dumps(sorted(set(file_lens))),
                "shape_tail": json.dumps(sorted({json.dumps(s[1:]) for s in shapes})),
                "chunk_shapes": json.dumps(sorted({json.dumps(c) for c in chunks})),
                "units": g.units.iloc[0],
                "calendar": g.calendar.iloc[0],
            }
        )
    return pd.DataFrame(rows)


def check_axes(sig: pd.DataFrame) -> None:
    for grp, g in sig.groupby("group"):
        # dominant axis = the one most variables use
        dom = g.axis_sha1.value_counts().index[0]
        d = g[g.axis_sha1 == dom].iloc[0]
        for r in g[g.axis_sha1 != dom].itertuples():
            why = []
            if r.ntime != d.ntime:
                why.append(f"ntime {r.ntime} vs {d.ntime}")
            if r.first != d.first:
                why.append(f"starts {r.first} vs {d.first}")
            if r.last != d.last:
                why.append(f"ends {r.last} vs {d.last}")
            if r.n_unique != r.ntime:
                why.append(f"{r.ntime - r.n_unique} duplicated stamps")
            if not why:
                why.append("same length and range but different time values (stamp placement)")
            add("single-group", "time-axis-differs-from-group", grp, r.var, [], "; ".join(why), n_files=r.n_files)
        if g.axis_sha1.nunique() > 1:
            summary = g.groupby("axis_sha1").agg(n=("var", "size"), ntime=("ntime", "first"),
                                                 first=("first", "first"), last=("last", "first"))
            add("single-group", "time-axis-clusters", grp, None, [],
                " | ".join(f"{r.n} vars: {r.ntime} steps {r.first}..{r.last}" for r in summary.itertuples()),
                n_files=int(g.n_files.sum()))
        # multi-file variables whose time chunk doesn't tile every file but the last
        for r in g[g.n_files > 1].itertuples():
            tc = json.loads(r.time_chunks)
            lens = json.loads(r.file_ntime)
            if len(tc) > 1:
                add("concat", "time-chunk-varies-across-files", grp, r.var, [], f"time chunks {tc}", n_files=r.n_files)
            elif tc and any(n % tc[0] for n in lens):
                add("concat", "time-chunk-does-not-divide-file-length", grp, r.var, [],
                    f"time chunk {tc[0]}, file lengths {lens}: every file ends in a partial chunk, so a "
                    "regular chunk grid can't concatenate them", n_files=r.n_files)
            if len(json.loads(r.chunk_shapes)) > 1:
                add("concat", "chunk-shape-varies-across-files", grp, r.var, [], r.chunk_shapes, n_files=r.n_files)
        ends = g.groupby("last")["var"].apply(list)
        if len(ends) > 1:
            add("single-group", "series-end-dates-differ", grp, None, [],
                " | ".join(f"{k}: {len(v)} vars" + (f" ({', '.join(v[:4])})" if len(v) < 6 else "") for k, v in ends.items()))


# ---------------------------------------------------------------- per-variable series
def check_series(prim: pd.DataFrame, files: pd.DataFrame) -> None:
    p = prim.merge(files[["key", "group"]], on="key")
    for (grp, var), g in p.groupby(["group", "var"]):
        if len(g) < 2:
            continue
        for col, cat in (("filters", "concat"), ("dtype", "concat"), ("h5_fillvalue", "concat"), ("fill_attr", "concat"),
                         ("scale_factor", "concat"), ("add_offset", "concat"), ("dims", "concat"),
                         ("units", "hygiene"), ("long_name", "hygiene"), ("layout", "concat")):
            vc = g[col].fillna("None").value_counts()
            if len(vc) > 1:
                add(cat, f"{col}-varies-across-files", grp, var, g.key,
                    " | ".join(f"{k}: {n}" for k, n in vc.items()))
        shp = g["shape"].map(lambda s: json.dumps(json.loads(s)[1:]))
        if shp.nunique() > 1:
            add("concat", "spatial-shape-varies-across-files", grp, var, g.key,
                " | ".join(f"{k}: {n}" for k, n in shp.value_counts().items()))
    # contiguous (unchunked) data variables of meaningful size
    big = p[(p.layout == "contiguous") & (p.ndim >= 2)]
    for grp, g in big.groupby("group"):
        add("hygiene", "contiguous-data-variable", grp, None, g.key,
            f"{g['var'].nunique()} vars stored unchunked, e.g. {g['var'].iloc[0]} {g['shape'].iloc[0]}")


def check_chunk_sizes(prim: pd.DataFrame, files: pd.DataFrame) -> None:
    """Uncompressed chunk size of each primary variable, flagged outside 1-100 MB."""
    p = prim[prim.chunks.notna()].merge(files[["key", "group"]], on="key")
    p = p.assign(mb=[np.prod(json.loads(c)) * np.dtype(d).itemsize / 1e6 for c, d in zip(p.chunks, p["dtype"])])
    per_var = p.drop_duplicates(["group", "var"])
    for grp, g in per_var.groupby("group"):
        for label, bad in (("over 100 MB", g[g.mb > 100]), ("under 1 MB", g[g.mb < 1])):
            if len(bad):
                ex = bad.iloc[0]
                add("chunking", "chunk-size-outside-1-100MB", grp, None, [],
                    f"{len(bad)} of {len(g)} variables have chunks {label} uncompressed, "
                    f"e.g. {ex['var']} chunks {ex.chunks} = {ex.mb:.1f} MB", n_files=len(bad))


def check_chunk_shapes(prim: pd.DataFrame, files: pd.DataFrame) -> None:
    """Distinct chunk shapes among same-rank variables of one release, and netCDF-C defaults.

    netCDF-C's default chunking targets 4 MiB and derives the shape from the dimension
    sizes, so shapes like [38, 255, 107] at 4.1-4.19 MB mean no chunking was specified.
    """
    p = prim[prim.chunks.notna()].merge(files[["key", "group"]], on="key")
    p = p.assign(
        rank=p["shape"].map(lambda s: len(json.loads(s))),
        bytes=[np.prod(json.loads(c)) * np.dtype(d).itemsize for c, d in zip(p.chunks, p["dtype"])],
    )
    for (grp, rank), g in p.drop_duplicates(["group", "var"]).groupby(["group", "rank"]):
        shapes = g.chunks.value_counts()
        default = g[(g["bytes"] > 4.0e6) & (g["bytes"] <= 4194304)]
        if len(shapes) > 1 or len(default):
            add("chunking", "chunk-shapes-within-release", grp, None, [],
                f"{rank}-D variables: {len(shapes)} chunk shapes ("
                + "; ".join(f"{k} x{n}" for k, n in shapes.head(5).items())
                + (" ..." if len(shapes) > 5 else "") + ")"
                + (f"; {len(default)} of {len(g)} look like netCDF-C default chunking (~4 MiB)" if len(default) else ""),
                n_files=len(g))


def check_dim_names(prim: pd.DataFrame, files: pd.DataFrame) -> None:
    """The ocean tracer grid named both jh/ih and yh/xh in one release.

    yT/xT, yB/xB (sea-ice model) and the q-point dims are legitimately separate names,
    so only the two spellings of the ocean h-point grid are compared.
    """
    p = prim[prim["ndim"] >= 3].merge(files[["key", "group"]], on="key").drop_duplicates(["group", "var"])
    p = p.assign(dims_=p.dims.map(json.loads))
    for grp, g in p.groupby("group"):
        ji = g[g.dims_.map(lambda d: "jh" in d or "ih" in d)]
        yx = g[g.dims_.map(lambda d: "yh" in d or "xh" in d)]
        if len(ji) and len(yx):
            add("single-group", "dimension-names-differ", grp, None, [],
                f"ocean tracer grid named jh/ih in {len(ji)} variables and yh/xh in {len(yx)} "
                f"(e.g. {ji['var'].iloc[0]} vs {yx['var'].iloc[0]})", n_files=len(ji) + len(yx))


def check_chunk_exceeds_shape(vars_: pd.DataFrame, files: pd.DataFrame) -> None:
    """A chunk longer than its array along a dimension (typical for unlimited dims).

    VirtualiZarr reads these fine but refuses to concatenate them, because the
    oversized chunk can't form a regular chunk grid across files.
    """
    v = vars_[vars_.chunks.notna() & (vars_.ndim > 0)].merge(files[["key", "group"]], on="key")
    over = [any(c > s for c, s in zip(json.loads(ch), json.loads(sh))) for ch, sh in zip(v.chunks, v["shape"])]
    v = v[over]
    v = v.assign(short=v.vname.str.split("/").str[-1])
    for grp, g in v.groupby("group"):
        ex = g.drop_duplicates("short").head(4)
        add("concat", "chunk-larger-than-array", grp, None, g.key,
            f"{g.short.nunique()} variable names in {g.key.nunique()} files, e.g. "
            + "; ".join(f"{r.short} shape {r.shape} chunks {r.chunks}" for r in ex.itertuples()))


def check_group_codecs(prim: pd.DataFrame, files: pd.DataFrame) -> None:
    """Across variables in a group: informational spread of codecs/dtypes/chunk shapes."""
    p = prim.merge(files[["key", "group"]], on="key")
    for grp, g in p.groupby("group"):
        for col in ("filters", "dtype"):
            vc = g.groupby(col)["var"].unique()
            if len(vc) > 1:
                add("hygiene", f"{col}-differ-between-variables", grp, None, [],
                    " | ".join(f"{k}: {', '.join(v[:4])}{' ...' if len(v) > 4 else ''} ({len(v)})" for k, v in vc.items()),
                    n_files=len(g))


# ---------------------------------------------------------------- grids + bundled vars
def check_coords(vars_: pd.DataFrame, files: pd.DataFrame) -> None:
    v = vars_.merge(files[["key", "group", "var"]], on="key")
    short = v.vname.str.split("/").str[-1]
    for name in COORD_1D + ("geolon", "geolat"):
        c = v[short == name]
        for grp, g in c.groupby("group"):
            col = "values_sha1" if name in ("geolon", "geolat") else "values_hash"
            vc = g[col].value_counts()
            if len(vc) > 1:
                examples = []
                for sha, n in vc.items():
                    r = g[g[col] == sha].iloc[0]
                    examples.append(f"{n} files n={r.nvalues} [{r['first']}..{r['last']}] e.g. {r['var']}")
                add("single-group", "coordinate-values-differ", grp, name, [], " | ".join(examples), n_files=len(g))


def check_bundled(vars_: pd.DataFrame, files: pd.DataFrame) -> None:
    v = vars_.merge(files[["key", "group", "var"]], on="key")
    v = v[v["var"].notna()]
    short = v.vname.str.split("/").str[-1]
    dimscales = set(COORD_1D) | {"time", "lead", "nv", "bnds"}
    extra = v[(short != v["var"]) & ~short.isin(AUX_VARS) & ~short.isin(dimscales)]
    dedicated = files.groupby("group")["var"].apply(set).to_dict()
    for (grp, name), g in extra.groupby(["group", extra.vname.str.split("/").str[-1]]):
        has_own = name in dedicated.get(grp, set())
        add("single-group" if has_own else "hygiene", "bundled-extra-variable", grp, name, g.key,
            f"in {g['var'].nunique()} other variables' files (shapes {sorted(g['shape'].unique())[:3]})"
            + ("; it also has its own file, so a naive merge sees two copies" if has_own else ""))


# ---------------------------------------------------------------- forecasts
def check_forecasts(files: pd.DataFrame, vars_: pd.DataFrame, axes: pd.DataFrame) -> None:
    fc = files[files.name_pattern == "forecast"]
    if fc.empty:
        return
    v = vars_.merge(fc[["key", "group", "var", "init"]], on="key")
    prim = v[v.vname == v["var"]]
    for grp, g in prim.groupby("group"):
        for col in ("dims", "shape", "chunks", "filters"):
            vc = g[col].map(lambda s: s if col != "shape" else json.dumps(json.loads(s)[:2])).value_counts()
            if len(vc) > 1:
                add("concat", f"forecast-{col}-varies", grp, None, [],
                    " | ".join(f"{k}: {n}" for k, n in vc.head(6).items()), n_files=len(g))
        # an init schedule is a set of months repeated every year; flag years that break it
        inits = sorted(g.init.unique())
        by_year = defaultdict(set)
        for i in inits:
            by_year[i[:4]].add(int(i[4:]))
        years = sorted(by_year)
        inner = [by_year[y] for y in years[1:-1]] or [by_year[y] for y in years]
        usual = Counter(frozenset(m) for m in inner).most_common(1)[0][0]
        odd = [y for y in years[1:-1] if by_year[y] != usual]
        if odd:
            add("concat", "forecast-init-schedule-irregular", grp, None, [],
                f"usual init months {sorted(usual)}; years that differ: "
                + ", ".join(f"{y} {sorted(by_year[y])}" for y in odd[:6]), n_files=len(g))
        dims = g.dims.map(lambda d: json.loads(d)[:2]).map(tuple).value_counts()
        add("hygiene", "forecast-schedule-and-layout", grp, None, [],
            f"{len(inits)} inits {inits[0]}..{inits[-1]}, init months {sorted(usual)}; "
            f"leading dims {', '.join('/'.join(k) for k in dims.index)}", n_files=len(g))
        per_var = g.groupby("var").init.nunique()
        if per_var.nunique() > 1:
            add("single-group", "forecast-vars-have-different-init-sets", grp, None, [],
                f"init counts per var: {per_var.value_counts().to_dict()}; fewest: {per_var.idxmin()} ({per_var.min()})",
                n_files=len(g))
    lead = axes[axes.vname == "lead"].merge(fc[["key", "group", "init"]], on="key")
    for grp, g in lead.groupby("group"):
        units = g.units.fillna("None").map(lambda u: re.sub(r"\d{4}-\d{2}-\d{2}.*", "<date>", u)).value_counts()
        n = g["values"].map(len).value_counts()
        # decoded, "days since <init>" units turn identical numbers into different dates per init
        rel = g["values"].map(lambda x: round(x[0], 3)).nunique() == 1 and g.units.fillna("").nunique() == 1
        add("hygiene" if rel else "concat", "forecast-lead-encoding", grp, "lead", [],
            f"units {units.to_dict()}; lengths {n.to_dict()}; "
            + ("lead identical across inits" if rel else
               "lead decodes to absolute dates that change with each init (units 'days since <init>'), "
               "so inits can't share one lead coordinate without decode_times=False or re-encoding"),
            n_files=len(g))


def main() -> None:
    inv = pd.read_parquet(OUT / "inventory.parquet")
    files = pd.read_parquet(OUT / "files.parquet")
    vars_ = pd.read_parquet(OUT / "vars.parquet")
    axes = pd.read_parquet(OUT / "axes.parquet")

    check_inventory(inv)
    check_kerchunk(inv)
    check_smoke()
    prim = check_files(files, vars_)
    t = time_table(files, axes)
    check_time_per_file(t)
    sig = axis_signatures(t, files, prim)
    sig.to_csv(OUT / "time_axes.csv", index=False)
    check_axes(sig)
    check_series(prim, files)
    check_group_codecs(prim, files)
    check_chunk_sizes(prim, files)
    check_chunk_shapes(prim, files)
    check_dim_names(prim, files)
    check_chunk_exceeds_shape(vars_, files)
    check_coords(vars_, files)
    check_bundled(vars_, files)
    check_forecasts(files, vars_, axes)

    df = pd.DataFrame(FINDINGS)
    df.to_csv(OUT / "findings.csv", index=False)
    print(df.groupby(["category", "check"]).size().to_string())


if __name__ == "__main__":
    main()
