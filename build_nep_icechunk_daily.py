#!/usr/bin/env python
"""
Build a CEFI NE Pacific Icechunk repository from public NOAA CEFI NetCDF files.

Minimal run-all usage:

    python build_cefi_nep_icechunk.py \
        --freq daily \
        --grid regrid \
        --release r20250912 \
        --creds source-cefi-creds.json

The variable manifest is cached with a source-file hash. If the source release
changes, or the file list changes, the cache is rebuilt automatically.

"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import icechunk
import pandas as pd
import s3fs
import xarray as xr
from obstore.store import from_url
from virtualizarr import open_virtual_dataset
from virtualizarr.parsers import HDFParser
from virtualizarr.registry import ObjectStoreRegistry


SOURCE_BUCKET = "s3://noaa-oar-cefi-regional-mom6-pds"
SOURCE_REGION = "us-east-1"

ICECHUNK_BUCKET = "us-west-2.opendata.source.coop"
ICECHUNK_PREFIX = "eeholmes/cefi/nepacific-icechunk"
ICECHUNK_REGION = "us-west-2"


def log(msg: str) -> None:
    print(msg, flush=True)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Create/update CEFI NE Pacific Icechunk groups from public NetCDF files."
    )
    p.add_argument("--freq", choices=["daily", "monthly"], required=True)
    p.add_argument("--grid", choices=["raw", "regrid"], required=True)
    p.add_argument("--release", required=True, help="Source release, e.g. r20250912")
    p.add_argument("--creds", default="source-cefi-creds.json")
    p.add_argument("--repo-prefix", default=ICECHUNK_PREFIX)
    p.add_argument("--branch", default="main")
    p.add_argument("--refresh-manifest", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--skip-existing-groups",
        action="store_true",
        help="Do not rewrite groups that already exist in the Icechunk store.",
    )
    return p.parse_args()


def source_prefix(freq: str, grid: str, release: str) -> str:
    return f"northeast_pacific/full_domain/hindcast/{freq}/{grid}/{release}"


def source_manifest_path(freq: str, grid: str, release: str) -> Path:
    return Path(f"cefi_nep_{freq}_{grid}_{release}_manifest.json")


def list_source_files(prefix: str) -> list[dict[str, Any]]:
    fs = s3fs.S3FileSystem(anon=True)
    rows = fs.ls(f"{SOURCE_BUCKET}/{prefix}", detail=True)
    files = []
    for row in rows:
        name = row["name"]
        if name.endswith(".nc"):
            files.append(
                {
                    "url": name if name.startswith("s3://") else f"s3://{name}",
                    "size": row.get("Size") or row.get("size"),
                    "etag": row.get("ETag") or row.get("etag"),
                    "last_modified": str(row.get("LastModified") or row.get("last_modified")),
                }
            )
    return sorted(files, key=lambda x: x["url"])


def manifest_hash(files: list[dict[str, Any]]) -> str:
    payload = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def var_from_filename(url: str, freq: str, grid: str) -> str:
    name = Path(url).name
    marker = f".nep.full.hcast.{freq}.{grid}"
    return name.split(marker)[0]


def group_urls_by_var(files: list[dict[str, Any]], freq: str, grid: str) -> dict[str, list[str]]:
    by_var: dict[str, list[str]] = defaultdict(list)
    for f in files:
        by_var[var_from_filename(f["url"], freq, grid)].append(f["url"])
    return {k: sorted(v) for k, v in sorted(by_var.items())}


def load_or_build_manifest(
    *,
    freq: str,
    grid: str,
    release: str,
    files: list[dict[str, Any]],
    registry: ObjectStoreRegistry,
    parser: HDFParser,
    refresh: bool = False,
) -> dict[str, Any]:
    """
    Cache variable groups, but invalidate the cache whenever the release/file list changes.

    For daily data, grouping by file count is fast.
    For monthly data, variables can have the same file count but different time lengths,
    so this opens metadata once per variable and groups by ntime.
    """
    cache_path = source_manifest_path(freq, grid, release)
    current_hash = manifest_hash(files)

    if cache_path.exists() and not refresh:
        cached = json.loads(cache_path.read_text())
        if cached.get("source_hash") == current_hash:
            log(f"Manifest cache OK: {cache_path}")
            return cached
        log(f"Manifest cache stale: {cache_path}; rebuilding")

    by_var = group_urls_by_var(files, freq, grid)

    if freq == "daily":
        vars_by_file_count: dict[str, list[str]] = defaultdict(list)
        for var, urls in by_var.items():
            vars_by_file_count[str(len(urls))].append(var)

        groups = {
            "vars_yearly": sorted(vars_by_file_count.get("33", [])),
            "vars_full_period": sorted(vars_by_file_count.get("1", [])),
            "vars_by_file_count": {k: sorted(v) for k, v in vars_by_file_count.items()},
        }

    else:
        vars_by_ntime: dict[str, list[str]] = defaultdict(list)
        skipped: dict[str, str] = {}

        log("Building monthly time-length manifest; this can take a while.")
        for i, (var, urls) in enumerate(by_var.items(), start=1):
            try:
                vds = open_virtual_dataset(
                    url=urls[0],
                    parser=parser,
                    registry=registry,
                    loadable_variables=["time"],
                    decode_times=True,
                )
                ntime = str(vds.sizes["time"])
                vars_by_ntime[ntime].append(var)
                log(f"  {i:03d}/{len(by_var):03d} {var}: ntime={ntime}")
            except Exception as e:
                skipped[var] = repr(e)
                log(f"  {i:03d}/{len(by_var):03d} {var}: SKIP {type(e).__name__}")

        groups = {
            "vars_by_ntime": {k: sorted(v) for k, v in sorted(vars_by_ntime.items())},
            # Backward-compatible names for the old monthly_raw_groups.json habit.
            "vars_390": sorted(vars_by_ntime.get("390", [])),
            "vars_396": sorted(vars_by_ntime.get("396", [])),
            "skipped": skipped,
        }

    manifest = {
        "freq": freq,
        "grid": grid,
        "release": release,
        "source_bucket": SOURCE_BUCKET,
        "source_prefix": source_prefix(freq, grid, release),
        "source_hash": current_hash,
        "n_files": len(files),
        "n_vars": len(by_var),
        "files": files,
        "urls_by_var": by_var,
        **groups,
    }

    cache_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    log(f"Wrote manifest: {cache_path}")
    return manifest


def time_is_good(vds: xr.Dataset) -> bool:
    t = pd.Index(vds.time.values)
    return t.is_unique and t.is_monotonic_increasing


def configure_virtualizarr() -> tuple[ObjectStoreRegistry, HDFParser, icechunk.RepositoryConfig]:
    remote_store = from_url(SOURCE_BUCKET, region=SOURCE_REGION, skip_signature=True)
    registry = ObjectStoreRegistry({SOURCE_BUCKET: remote_store})
    parser = HDFParser()

    config = icechunk.RepositoryConfig.default()
    config.set_virtual_chunk_container(
        icechunk.VirtualChunkContainer(
            url_prefix=SOURCE_BUCKET.rstrip("/") + "/",
            store=icechunk.s3_store(region=SOURCE_REGION, anonymous=True),
        )
    )
    return registry, parser, config


def open_repo(creds_path: str, repo_prefix: str, config: icechunk.RepositoryConfig) -> icechunk.Repository:
    creds = json.loads(Path(creds_path).read_text())
    storage = icechunk.s3_storage(
        bucket=ICECHUNK_BUCKET,
        prefix=repo_prefix,
        region=creds.get("region_name", ICECHUNK_REGION),
        access_key_id=creds["aws_access_key_id"],
        secret_access_key=creds["aws_secret_access_key"],
        session_token=creds["aws_session_token"],
    )

    try:
        repo = icechunk.Repository.create(storage, config)
        log("Repo: created")
    except Exception:
        repo = icechunk.Repository.open(storage, config=config)
        log("Repo: opened existing")

    return repo


def group_exists(repo: icechunk.Repository, branch: str, group: str) -> bool:
    try:
        import zarr

        session = repo.readonly_session(branch=branch)
        root = zarr.open_group(session.store, mode="r")
        cur = root
        for part in group.split("/"):
            if part not in cur:
                return False
            cur = cur[part]
        return True
    except Exception:
        return False


def open_one_var(
    *,
    var: str,
    url: str,
    registry: ObjectStoreRegistry,
    parser: HDFParser,
    loadable_variables: list[str],
) -> xr.Dataset:
    return (
        open_virtual_dataset(
            url=url,
            parser=parser,
            registry=registry,
            loadable_variables=loadable_variables,
            decode_times=True,
        )
        .drop_vars(["nv", "ncrs", "crs"], errors="ignore")[[var]]
    )


def write_daily(
    *,
    repo: icechunk.Repository,
    branch: str,
    grid: str,
    release: str,
    manifest: dict[str, Any],
    registry: ObjectStoreRegistry,
    parser: HDFParser,
    skip_existing: bool,
) -> None:
    yearly_vars = manifest["vars_yearly"]
    full_vars = manifest["vars_full_period"]
    urls_by_var = manifest["urls_by_var"]

    if yearly_vars:
        group = f"daily/{grid}/{release}/main"
        if skip_existing and group_exists(repo, branch, group):
            log(f"SKIP existing group: {group}")
        else:
            template_var = "chlos" if "chlos" in yearly_vars else yearly_vars[0]
            n_blocks = min(len(urls_by_var[v]) for v in yearly_vars)
            log(f"Writing {group}: {len(yearly_vars)} vars × {n_blocks} yearly blocks")

            session = repo.writable_session(branch=branch)
            for year_index in range(n_blocks):
                t0 = time.time()
                template_vds = open_virtual_dataset(
                    url=urls_by_var[template_var][year_index],
                    parser=parser,
                    registry=registry,
                    loadable_variables=["time", "lat", "lon", "z_l"],
                    decode_times=True,
                ).drop_vars(["nv", "ncrs", "crs"], errors="ignore")
                template_time = template_vds.time

                vds_list = []
                repaired = []
                for var in yearly_vars:
                    vds = open_one_var(
                        var=var,
                        url=urls_by_var[var][year_index],
                        registry=registry,
                        parser=parser,
                        loadable_variables=["time", "lat", "lon", "z_l"],
                    )
                    if not time_is_good(vds):
                        vds = vds.assign_coords(time=template_time)
                        repaired.append(var)
                    vds_list.append(vds)

                combined = xr.merge(
                    vds_list,
                    compat="override",
                    join="exact",
                    combine_attrs="drop_conflicts",
                )
                kwargs = {} if year_index == 0 else {"append_dim": "time"}
                combined.vz.to_icechunk(session.store, group=group, **kwargs)

                snapshot = session.commit(f"{release}: append daily {grid} main block {year_index + 1}")
                elapsed = time.time() - t0
                extra = f"; repaired={len(repaired)}" if repaired else ""
                log(f"  block {year_index + 1:02d}/{n_blocks}: committed {snapshot} ({elapsed:.1f}s{extra})")

                if year_index != n_blocks - 1:
                    session = repo.writable_session(branch=branch)

    if full_vars:
        group = f"daily/{grid}/{release}/aux"
        if skip_existing and group_exists(repo, branch, group):
            log(f"SKIP existing group: {group}")
        else:
            log(f"Writing {group}: {len(full_vars)} full-period vars")
            session = repo.writable_session(branch=branch)
            vds_list = []
            bad_time = []
            for var in full_vars:
                vds = open_one_var(
                    var=var,
                    url=urls_by_var[var][0],
                    registry=registry,
                    parser=parser,
                    loadable_variables=["time", "lat", "lon"],
                )
                if not time_is_good(vds):
                    bad_time.append(var)
                vds_list.append(vds)

            combined = xr.merge(
                vds_list,
                compat="override",
                join="exact",
                combine_attrs="drop_conflicts",
            )
            combined.vz.to_icechunk(session.store, group=group)
            snapshot = session.commit(f"{release}: write daily {grid} aux")
            log(f"  committed {snapshot}; bad_time={len(bad_time)}")


def write_monthly(
    *,
    repo: icechunk.Repository,
    branch: str,
    grid: str,
    release: str,
    manifest: dict[str, Any],
    registry: ObjectStoreRegistry,
    parser: HDFParser,
    skip_existing: bool,
) -> None:
    urls_by_var = manifest["urls_by_var"]
    vars_by_ntime = manifest["vars_by_ntime"]

    for ntime, vars_for_group in sorted(vars_by_ntime.items(), key=lambda kv: int(kv[0])):
        group = f"monthly/{grid}/{release}/time_{ntime}"
        if skip_existing and group_exists(repo, branch, group):
            log(f"SKIP existing group: {group}")
            continue

        log(f"Writing {group}: {len(vars_for_group)} vars")
        session = repo.writable_session(branch=branch)
        vds_list = []
        bad_time = []

        for var in vars_for_group:
            loadable = ["time", "lat", "lon", "z_l"]
            vds = open_one_var(
                var=var,
                url=urls_by_var[var][0],
                registry=registry,
                parser=parser,
                loadable_variables=loadable,
            )
            if not time_is_good(vds):
                bad_time.append(var)
            vds_list.append(vds)

        combined = xr.merge(
            vds_list,
            compat="override",
            join="exact",
            combine_attrs="drop_conflicts",
        )
        combined.vz.to_icechunk(session.store, group=group)
        snapshot = session.commit(f"{release}: write monthly {grid} time_{ntime}")
        log(f"  committed {snapshot}; bad_time={len(bad_time)}")


def main() -> int:
    args = parse_args()
    prefix = source_prefix(args.freq, args.grid, args.release)

    log(f"Source: {SOURCE_BUCKET}/{prefix}")
    files = list_source_files(prefix)
    if not files:
        raise RuntimeError(f"No NetCDF files found under {SOURCE_BUCKET}/{prefix}")
    log(f"Found {len(files)} NetCDF files")

    registry, parser, config = configure_virtualizarr()

    manifest = load_or_build_manifest(
        freq=args.freq,
        grid=args.grid,
        release=args.release,
        files=files,
        registry=registry,
        parser=parser,
        refresh=args.refresh_manifest,
    )

    if args.freq == "daily":
        log(
            "Daily manifest: "
            f"{len(manifest['vars_yearly'])} yearly vars, "
            f"{len(manifest['vars_full_period'])} full-period vars"
        )
    else:
        counts = ", ".join(f"{k}: {len(v)} vars" for k, v in manifest["vars_by_ntime"].items())
        log(f"Monthly manifest: {counts}")

    if args.dry_run:
        log("Dry run complete; no Icechunk writes performed.")
        return 0

    repo = open_repo(args.creds, args.repo_prefix, config)

    if args.freq == "daily":
        write_daily(
            repo=repo,
            branch=args.branch,
            grid=args.grid,
            release=args.release,
            manifest=manifest,
            registry=registry,
            parser=parser,
            skip_existing=args.skip_existing_groups,
        )
    else:
        write_monthly(
            repo=repo,
            branch=args.branch,
            grid=args.grid,
            release=args.release,
            manifest=manifest,
            registry=registry,
            parser=parser,
            skip_existing=args.skip_existing_groups,
        )

    log("Done.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        log("Interrupted.")
        raise SystemExit(130)
