#!/usr/bin/env python
"""
Build the monthly CEFI NE Pacific Icechunk groups from public NOAA NetCDF files.

Stable Icechunk group paths:

    monthly/{grid}/main   # variables with 390 monthly time steps
    monthly/{grid}/aux1   # variables with 396 monthly time steps
    monthly/{grid}/aux2   # sisnmass, if requested/present

The source release is used only to find input files and validate the local
manifest cache. Versioning is handled with Icechunk snapshot tags.


Example:

    python build_cefi_nep_monthly.py \
      --grid raw \
      --release r20250819 \
      --creds source-cefi-creds.json \
      --max-token-minutes 45
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import icechunk
import pandas as pd
import s3fs
import xarray as xr
import zarr
from obstore.store import from_url
from obspec_utils.registry import ObjectStoreRegistry
from virtualizarr import open_virtual_dataset
from virtualizarr.parsers import HDFParser
from virtualizarr.writers.icechunk import write_virtual_dataset_to_icechunk_group


SOURCE_BUCKET = "s3://noaa-oar-cefi-regional-mom6-pds"
SOURCE_REGION = "us-east-1"

ICECHUNK_BUCKET = "us-west-2.opendata.source.coop"
ICECHUNK_PREFIX = "eeholmes/cefi/nepacific-icechunk"
ICECHUNK_REGION = "us-west-2"

# Keep these paths stable. Do not put source releases in the group names.
MONTHLY_GROUPS_BY_NTIME = {
    390: "main",
    396: "aux1",
}


def log(msg: str) -> None:
    print(msg, flush=True)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Create/update monthly CEFI NE Pacific Icechunk groups."
    )
    p.add_argument("--grid", choices=["raw", "regrid"], default="regrid")
    p.add_argument("--release", required=True, help="Source release, e.g. r20250912")
    p.add_argument("--creds", default="source-cefi-creds.json")
    p.add_argument("--repo-prefix", default=ICECHUNK_PREFIX)
    p.add_argument("--branch", default="main")
    p.add_argument("--batch-size", type=int, default=5)
    p.add_argument("--refresh-manifest", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--tag", default=None, help="Optional Icechunk tag, e.g. v1.0.0")
    p.add_argument(
        "--no-sisnmass-aux2",
        action="store_true",
        help="Do not write sisnmass to monthly/{grid}/aux2.",
    )
    return p.parse_args()


def source_prefix(grid: str, release: str) -> str:
    return f"northeast_pacific/full_domain/hindcast/monthly/{grid}/{release}"


def manifest_path(grid: str, release: str) -> Path:
    return Path(f"cefi_nep_monthly_{grid}_{release}_manifest.json")


def list_source_files(grid: str, release: str) -> list[dict[str, Any]]:
    prefix = source_prefix(grid, release)
    fs = s3fs.S3FileSystem(anon=True)
    rows = fs.ls(f"{SOURCE_BUCKET}/{prefix}", detail=True)

    files: list[dict[str, Any]] = []
    for row in rows:
        name = row["name"]
        if not name.endswith(".nc"):
            continue
        files.append(
            {
                "url": name if name.startswith("s3://") else f"s3://{name}",
                "size": row.get("Size") or row.get("size"),
                "etag": row.get("ETag") or row.get("etag"),
                "last_modified": str(row.get("LastModified") or row.get("last_modified")),
            }
        )
    return sorted(files, key=lambda x: x["url"])


def file_list_hash(files: list[dict[str, Any]]) -> str:
    payload = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def var_from_url(url: str, grid: str) -> str:
    name = Path(url).name
    marker = f".nep.full.hcast.monthly.{grid}"
    if marker not in name:
        raise ValueError(f"Unexpected monthly filename: {name}")
    return name.split(marker)[0]


def urls_by_var(files: list[dict[str, Any]], grid: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for f in files:
        out[var_from_url(f["url"], grid)].append(f["url"])
    return {k: sorted(v) for k, v in sorted(out.items())}


def configure_io() -> tuple[ObjectStoreRegistry, HDFParser, icechunk.RepositoryConfig]:
    store = from_url(SOURCE_BUCKET, region=SOURCE_REGION, skip_signature=True)
    registry = ObjectStoreRegistry({SOURCE_BUCKET: store})
    parser = HDFParser()

    config = icechunk.RepositoryConfig.default()
    config.set_virtual_chunk_container(
        icechunk.VirtualChunkContainer(
            url_prefix=f"{SOURCE_BUCKET}/",
            store=icechunk.s3_store(region=SOURCE_REGION, anonymous=True),
        )
    )
    return registry, parser, config


def load_or_build_manifest(
    *,
    grid: str,
    release: str,
    files: list[dict[str, Any]],
    registry: ObjectStoreRegistry,
    parser: HDFParser,
    refresh: bool,
) -> dict[str, Any]:
    path = manifest_path(grid, release)
    current_hash = file_list_hash(files)

    if path.exists() and not refresh:
        cached = json.loads(path.read_text())
        if cached.get("source_hash") == current_hash:
            log(f"Manifest cache OK: {path}")
            return cached
        log(f"Manifest cache stale: {path}; rebuilding")

    by_var = urls_by_var(files, grid)
    vars_by_ntime: dict[str, list[str]] = defaultdict(list)
    skipped: dict[str, str] = {}

    log("Building monthly manifest from variable metadata. This is the slow step.")
    for i, (var, urls) in enumerate(by_var.items(), start=1):
        if len(urls) != 1:
            skipped[var] = f"expected 1 file, found {len(urls)}"
            log(f"  {i:03d}/{len(by_var):03d} {var}: SKIP file_count={len(urls)}")
            continue

        try:
            vds = open_virtual_dataset(
                url=urls[0],
                parser=parser,
                registry=registry,
                loadable_variables=["time"],
                decode_times=True,
            )
            if "time" not in vds:
                skipped[var] = "no time coordinate"
                log(f"  {i:03d}/{len(by_var):03d} {var}: SKIP no time")
                continue
            ntime = str(vds.sizes["time"])
            vars_by_ntime[ntime].append(var)
            log(f"  {i:03d}/{len(by_var):03d} {var}: ntime={ntime}")
        except Exception as e:
            skipped[var] = repr(e)
            log(f"  {i:03d}/{len(by_var):03d} {var}: SKIP {type(e).__name__}")

    manifest = {
        "dataset": "cefi_nep_monthly",
        "grid": grid,
        "release": release,
        "source_bucket": SOURCE_BUCKET,
        "source_prefix": source_prefix(grid, release),
        "source_hash": current_hash,
        "n_files": len(files),
        "n_vars": len(by_var),
        "files": files,
        "urls_by_var": by_var,
        "vars_by_ntime": {k: sorted(v) for k, v in sorted(vars_by_ntime.items(), key=lambda kv: int(kv[0]))},
        "vars_390": sorted(vars_by_ntime.get("390", [])),
        "vars_396": sorted(vars_by_ntime.get("396", [])),
        "skipped": skipped,
    }
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    log(f"Wrote manifest: {path}")
    return manifest


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


def time_is_good(vds: xr.Dataset) -> bool:
    t = pd.Index(vds.time.values)
    return t.is_unique and t.is_monotonic_increasing


def batched(seq: list[str], n: int):
    for i in range(0, len(seq), n):
        yield i, seq[i : i + n]


def open_existing_group(session: icechunk.Session, group_name: str) -> zarr.Group:
    return zarr.open_group(
        store=session.store,
        path=group_name,
        mode="a",
        zarr_format=3,
    )


def get_existing_names(session: icechunk.Session, group_name: str) -> set[str]:
    try:
        group = open_existing_group(session, group_name)
    except Exception:
        return set()

    names: set[str] = set()
    for method in ("keys", "array_keys", "group_keys"):
        try:
            names.update(getattr(group, method)())
        except Exception:
            pass
    return names


def write_batch_to_group(
    *,
    session: icechunk.Session,
    group_name: str,
    vds_batch: xr.Dataset,
    group_already_exists: bool,
) -> None:
    if not group_already_exists:
        vds_batch.vz.to_icechunk(session.store, group=group_name)
        return

    group = open_existing_group(session, group_name)
    existing_names = get_existing_names(session, group_name)

    existing_coord_vars = [
        name
        for name in existing_names
        if name in vds_batch.variables and name not in vds_batch.data_vars
    ]
    if existing_coord_vars:
        vds_batch = vds_batch.drop_vars(existing_coord_vars, errors="ignore")

    write_virtual_dataset_to_icechunk_group(
        vds=vds_batch,
        store=session.store,
        group=group,
        append_dim=None,
        last_updated_at=None,
    )


def open_monthly_var(
    *,
    var: str,
    url: str,
    registry: ObjectStoreRegistry,
    parser: HDFParser,
    full_vds: bool,
) -> xr.Dataset:
    vds = open_virtual_dataset(
        url=url,
        parser=parser,
        registry=registry,
        loadable_variables=["time"],
        decode_times=True,
    )
    return vds if full_vds else vds[[var]]


def write_monthly_time_group(
    *,
    repo: icechunk.Repository,
    branch: str,
    grid: str,
    release: str,
    urls: dict[str, list[str]],
    vars_list: list[str],
    ntime: int,
    group_suffix: str,
    registry: ObjectStoreRegistry,
    parser: HDFParser,
    batch_size: int,
) -> str | None:
    if not vars_list:
        log(f"SKIP monthly/{grid}/{group_suffix}: no variables")
        return None

    group_name = f"monthly/{grid}/{group_suffix}"
    template_var = vars_list[0]
    template_url = urls[template_var][0]

    template_vds = open_virtual_dataset(
        url=template_url,
        parser=parser,
        registry=registry,
        loadable_variables=["time"],
        decode_times=True,
    )
    template_time = template_vds.time

    if template_vds.sizes["time"] != ntime:
        raise ValueError(f"Template {template_var} has {template_vds.sizes['time']} time steps, expected {ntime}")
    if not time_is_good(template_vds):
        raise ValueError(f"Template {template_var} has a bad time coordinate")

    log(f"Writing {group_name}: {len(vars_list)} vars, ntime={ntime}, template={template_var}")

    latest_snapshot: str | None = None
    written: list[str] = []
    skipped: list[tuple[str, str]] = []

    # We determine this from the store at the start of each batch. That makes reruns safe.
    for batch_start, batch_vars in batched(vars_list, batch_size):
        t0 = time.time()
        batch_num = batch_start // batch_size + 1
        session = repo.writable_session(branch=branch)
        existing_names = get_existing_names(session, group_name)
        group_already_exists = bool(existing_names)
        include_extra_vars_once = not group_already_exists

        vds_list = []
        batch_written: list[str] = []
        batch_skipped: list[tuple[str, str]] = []

        for var in batch_vars:
            if var in existing_names:
                batch_skipped.append((var, "already exists"))
                continue

            try:
                vds = open_monthly_var(
                    var=var,
                    url=urls[var][0],
                    registry=registry,
                    parser=parser,
                    full_vds=include_extra_vars_once,
                )
                if "time" not in vds.coords:
                    batch_skipped.append((var, "no time coordinate"))
                    continue
                if vds.sizes["time"] != ntime:
                    batch_skipped.append((var, f"ntime={vds.sizes['time']}"))
                    continue
                if not time_is_good(vds):
                    batch_skipped.append((var, "bad time coordinate"))
                    continue
                if not (vds.time.values == template_time.values).all():
                    batch_skipped.append((var, f"time mismatch with {template_var}"))
                    continue

                vds_list.append(vds)
                batch_written.append(var)
                include_extra_vars_once = False
            except Exception as e:
                batch_skipped.append((var, repr(e)))

        if not vds_list:
            skipped.extend(batch_skipped)
            log(f"  batch {batch_num}: no new variables")
            continue

        vds_batch = xr.merge(
            vds_list,
            compat="override",
            join="exact",
            combine_attrs="drop_conflicts",
        )
        write_batch_to_group(
            session=session,
            group_name=group_name,
            vds_batch=vds_batch,
            group_already_exists=group_already_exists,
        )
        snapshot = session.commit(
            f"{release}: add monthly {grid} {group_suffix} batch {batch_num}"
        )
        latest_snapshot = snapshot
        written.extend(batch_written)
        skipped.extend(batch_skipped)
        elapsed = time.time() - t0
        log(f"  batch {batch_num}: committed {snapshot}; wrote={len(batch_written)}, skipped={len(batch_skipped)} ({elapsed:.1f}s)")

    log(f"Summary {group_name}: written={len(written)}, skipped={len(skipped)}")
    if skipped:
        skipped_reasons = defaultdict(int)
        for _, reason in skipped:
            skipped_reasons[reason] += 1
        log("  skipped reasons: " + ", ".join(f"{k}={v}" for k, v in skipped_reasons.items()))

    return latest_snapshot


def write_sisnmass_aux2(
    *,
    repo: icechunk.Repository,
    branch: str,
    grid: str,
    release: str,
    urls: dict[str, list[str]],
    registry: ObjectStoreRegistry,
    parser: HDFParser,
) -> str | None:
    var = "sisnmass"
    if var not in urls:
        log("SKIP monthly aux2: sisnmass not found")
        return None

    group_name = f"monthly/{grid}/aux2"
    session = repo.writable_session(branch=branch)
    existing = get_existing_names(session, group_name)
    if var in existing:
        log(f"SKIP {group_name}: sisnmass already exists")
        return None

    vds = open_virtual_dataset(
        url=urls[var][0],
        parser=parser,
        registry=registry,
        loadable_variables=["time"],
        decode_times=True,
    )
    vds.vz.to_icechunk(session.store, group=group_name)
    snapshot = session.commit(f"{release}: write monthly {grid} aux2 sisnmass")
    log(f"Committed {group_name}: {snapshot}")
    return snapshot


def main() -> int:
    args = parse_args()
    prefix = source_prefix(args.grid, args.release)
    log(f"Source: {SOURCE_BUCKET}/{prefix}")

    files = list_source_files(args.grid, args.release)
    if not files:
        raise RuntimeError(f"No NetCDF files found under {SOURCE_BUCKET}/{prefix}")
    log(f"Found {len(files)} NetCDF files")

    registry, parser, config = configure_io()
    manifest = load_or_build_manifest(
        grid=args.grid,
        release=args.release,
        files=files,
        registry=registry,
        parser=parser,
        refresh=args.refresh_manifest,
    )

    counts = ", ".join(
        f"ntime {k}: {len(v)} vars" for k, v in manifest["vars_by_ntime"].items()
    )
    log(f"Monthly manifest: {counts}")
    if manifest.get("skipped"):
        log(f"Manifest skipped variables: {len(manifest['skipped'])}")

    unexpected = sorted(
        int(k) for k in manifest["vars_by_ntime"] if int(k) not in MONTHLY_GROUPS_BY_NTIME
    )
    if unexpected:
        log(f"WARNING: unexpected monthly time counts not written by default: {unexpected}")

    if args.dry_run:
        log("Dry run complete; no Icechunk writes performed.")
        return 0

    repo = open_repo(args.creds, args.repo_prefix, config)
    latest_snapshot: str | None = None

    for ntime, group_suffix in MONTHLY_GROUPS_BY_NTIME.items():
        snapshot = write_monthly_time_group(
            repo=repo,
            branch=args.branch,
            grid=args.grid,
            release=args.release,
            urls=manifest["urls_by_var"],
            vars_list=manifest["vars_by_ntime"].get(str(ntime), []),
            ntime=ntime,
            group_suffix=group_suffix,
            registry=registry,
            parser=parser,
            batch_size=args.batch_size,
        )
        latest_snapshot = snapshot or latest_snapshot

    if not args.no_sisnmass_aux2:
        snapshot = write_sisnmass_aux2(
            repo=repo,
            branch=args.branch,
            grid=args.grid,
            release=args.release,
            urls=manifest["urls_by_var"],
            registry=registry,
            parser=parser,
        )
        latest_snapshot = snapshot or latest_snapshot

    if args.tag:
        if not latest_snapshot:
            raise RuntimeError("No new snapshot was committed, so no tag was created.")
        repo.create_tag(name=args.tag, commit_id=latest_snapshot)
        log(f"Tagged {latest_snapshot} as {args.tag}")

    log("Done.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        log("Interrupted.")
        raise SystemExit(130)
