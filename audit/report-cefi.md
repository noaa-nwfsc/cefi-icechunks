# CEFI regional MOM6 source-file audit

Audit run 2026-09-23 against
`s3://noaa-oar-cefi-regional-mom6-pds` (anonymous).

**Scope.** The newest release of each product (region / experiment / frequency / grid).
The report covers the 18 Northeast Pacific (NEP) and Northwest Atlantic (NWA)
products: 6,783 NetCDFs (15.3 TB) and 6,880 Kerchunk JSONs. The four Pacific Islands
(PCI) products are still drafts and are not covered. Earlier releases are superseded and
not covered.

**Goal it serves.** One virtual Icechunk group per product holding every variable (for
example `nep/hindcast/monthly/regrid`). For each problem the question is whether it
stops a variable from joining that group, or stops a variable's files from being
added to an icechunk at all. What a rebuild of the files could fix, and what it would take, is in [Rebuilding the NetCDFs](#rebuilding-the-netcdfs); the details of each problem are in
[Appendix 1](#appendix-1-problem-details).

## Summary

- **The time axes are in good shape.** Every NEP and NWA hindcast product has a single
  time axis shared by all its variables. No duplicated or backwards time stamps were
  found.
- **There is no chunking standard, and that is the biggest problem.** The main variables
  use 19 different chunk shapes. 406 files use netCDF-C's automatic ~4 MiB chunking,
  meaning no chunking was chosen. The 4-D (depth-resolved) variables use 160 MB chunks
  (P1).
- **What else blocks one group per product:**
  - The daily **4-D (depth-resolved) variables** (`dissic`, `thetao`, `so`, `no3`, ...)
    are the only daily variables stored as one file per year. Their 100-step time chunk
    doesn't divide 365/366, so the years can't be joined on a regular chunk grid.
    **Earthmover's production daily store leaves every one of them out for this
    reason.** Appending them one year at a time instead runs without error but misplaces
    the data (P2; affected files listed in
    [Appendix 2](#appendix-2-files-affected-by-p2)).
  - A full 4-D `volcello` is bundled inside other variables' raw files, and NEP daily
    also carries a typo'd `vollcello` series (P3).
  - The static files are netCDF3 and have land-masked coordinates (P4).
  - NWA monthly regrid mixes two longitude grids (P5).
  - Forecast `lead` and `member` coordinates are inconsistent (P7, P8).
- **Kerchunk JSON content is sound; the problems are around it.** Every sampled JSON
  that exists and points at the right file (246 files) matched VirtualiZarr's manifest
  exactly. However:
  - 176 JSONs are empty.
  - 568 are misnamed (first character dropped).
  - 22 static-file JSONs point at **another region's or experiment's** static file
    (NEP's `ocean_stati.json` references the Pacific Islands `ocean_static.nc`, for
    example). Anyone using them silently gets the wrong grid.
  - 142 NetCDFs are referenced by no JSON at all.
  - Reference URLs mix `s3://` and bare paths (P9).
- **VirtualiZarr parses every HDF5 file sampled** (260 of 260). It fails only on the
  netCDF3 static files.

## Checked and found consistent

- **Time:** within each hindcast product, time units and calendar agree, and there are
  no duplicated, backwards or irregular time stamps (apart from P6).
- **Codecs and dtype:** every main variable is float32 with zlib level 2 and shuffle.
- **Files:** no HDF5 file failed to open, and none uses HDF5 subgroups.
- **Coordinates:** grid coordinates (`xh`, `yh`, `lat`, `lon`, `z_l`, ...) agree across
  a product's files, apart from P4, P5 and P8.
- **Decadal forecasts:** complete annual init series (1965–2025 in r20250925).

## Problems found

"Time axes" is the number of distinct time axes among a hindcast product's variables;
1 means every variable can share one time dimension. Problem codes (P1–P9) are
detailed in [Appendix 1](#appendix-1-problem-details). Kerchunk problems (P9) affect
nearly every product and aren't repeated here.

| Product | Release | .nc | Vars | Time axes | Problems |
|---|---|---:|---:|---:|---|
| nep hindcast daily raw | r20260701 | 414 | 28 | 1 | P1, P2, P3, P4 |
| nep hindcast daily regrid | r20260701 | 346 | 26 | 1 | P1, P2, P3 (`vollcello`) |
| nep hindcast monthly raw | r20260701 | 463 | 461 | 1 | P1, P3, P4 |
| nep hindcast monthly regrid | r20260701 | 437 | 437 | 1 | P1 |
| nwa hindcast daily raw | r20250715 | 13 | 11 | 1 | P4 |
| nwa hindcast daily regrid | r20250715 | 11 | 11 | 1 | none found |
| nwa hindcast monthly raw | r20250715 | 490 | 488 | 1 | P1, P3, P4 |
| nwa hindcast monthly regrid | r20250715 | 464 | 464 | 1 | P1, P5 |
| nwa multi-decadal yearly raw | r20260331 | 76 | 19 | 2 | P6 |
| nwa multi-decadal yearly regrid | r20260331 | 32 | 8 | 1 | none found |
| nwa decadal forecast monthly raw / regrid | r20250925 | 1100 / 1098 | 18 | – | P7, P4 (raw) |
| nwa decadal forecast yearly raw / regrid | r20250819 | 367 / 366 | 6 | – | P7 |
| nwa seasonal forecast monthly raw / regrid | r20250710 | 73 / 72 | 18 | – | P8, P4 (raw) |
| nwa seasonal reforecast monthly raw / regrid | r20250413 | 481 / 480 | 4 | – | P8, P4 (raw) |

## Rebuilding the NetCDFs

This section covers what a rebuild would fix, what it can't, and what the work would
take. Most fixes assume a common standard for chunking, encoding and naming, to be
agreed with the CEFI team; it is not a settled spec. The numbers come from the audit
and from timings on real files.

- **Most problems can be fixed by reprocessing the published files.** A handful can't:
  a missing ensemble member, a missing year, and variables regridded to a different
  longitude grid need CEFI to regenerate from model output.
- **Machine time for reprocessing.** Rewriting the newest release of every NEP and NWA
  product (about 36 TB uncompressed) is roughly **200–900 CPU core-hours**. On a fleet
  of about 25 VMs that is **under a day of wall-clock time**, including validation, for
  about **$40–100 of compute**.
- **The larger effort is people, not machines.** Implementation depends on agreeing the
  standard, writing and testing the pipeline, and piloting it.

### What a rebuild can and can't fix

"Reprocess" means rewriting the newest published files. "CEFI" means the data needed isn't in the bucket.

| Problem | Fix | Who |
|---|---|---|
| P1 chunk sizes and shapes; P2 per-year time chunks | Rewrite with standard chunks | Reprocess |
| P3 bundled `volcello`, typo'd `vollcello` | Drop bundled copies; keep one `volcello` (static or its own file) | Reprocess |
| P4 netCDF3 static files, masked `geolon`/`geolat` | Rewrite as netCDF4; take coordinates from the data files | Reprocess |
| P7 decadal `lead` as dates; P8 fill values, dimension order, bundled anomalies | Re-encode `lead` as months since init; one fill value; one dimension order | Reprocess |
| File naming, time units spelling | Normalize metadata and names | Reprocess |
| P5 NWA regrid variables on the 0.0801° grid | Re-regrid from raw onto the common grid (needs CEFI's regridding weights and method) | CEFI (or reprocess, with their weights) |
| P8 member 6 missing from seasonal forecast init 202510 | Regenerate | **CEFI** |
| P6 `T_adx` SSP585 missing 2045 | Regenerate | **CEFI** |
| P9 Kerchunk JSONs | Regenerate from rebuilt files, or retire the JSON workflow | CEFI decision |


## Appendix 1: Problem details

Each problem lists where it occurs, the evidence, why it matters for a virtual Icechunk
store, and the script under `audit/repro/` that reproduces it. Every finding is a row in
`audit/out/findings.csv`.

### P1. Chunking: no standard, and chunks too large
A virtual Icechunk store keeps the source files' chunks, so every read costs whatever the
NetCDF chunking dictates. Only rewriting the files can change it.

- **No standard.** The main variables use 19 distinct chunk shapes, which differ between
  regions, raw and regrid, and variables:

  | Chunk shape | Files | Uncompressed |
  |---|---:|---:|
  | `[10, 12, 200, 200]` | 1,578 | 19 MB |
  | `[100, 200, 200]` | 1,214 | 16 MB |
  | `[2, 30, 211, 194]` | 1,098 | 10 MB |
  | `[100, 10, 200, 200]` | 1,006 | 160 MB |
  | `[4, 4, 282, 258]` | 480 | 4.7 MB |
  | `[38, 255, 107]` (netCDF-C default) | 390 | 4.1 MB |
  | `[10, 10, 200, 200]` | 366 | 16 MB |
  | `[4, 4, 422, 387]` | 366 | 10.5 MB |
  | `[12, 10, 200, 200]` | 108 | 19 MB |
  | `[213, 109, 45]` (netCDF-C default) | 16 | 4.2 MB |
  | 9 other shapes | 148 | 3.5–80 MB |
  | **19 shapes** | **6,770** | |

- **Many files were written without a chunking choice.** 406 files use `[38, 255, 107]`
  (every 2-D NEP monthly raw variable) or `[213, 109, 45]` (every 2-D NEP daily raw
  variable), both just under 4 MiB. That is netCDF-C's default chunking, which targets
  4 MiB (4,194,304 bytes) and derives the shape from the dimension sizes.
- **Too large (NEP and NWA 4-D).** `[100, 10, 200, 200]` is 160 MB uncompressed. NEP
  monthly `thetao` chunks are 27 MB compressed at the median and up to 94 MB; NWA regrid
  `thetao` is 16 MB median, up to 84 MB. Reading one time step at one level pulls the
  whole chunk.
- **Chunks that don't fit the data.** Time chunks of 100 don't align with years or
  months (P2). Spatial tiles of 200 don't divide the grids (816 × 342, 845 × 775), so
  every file has ragged edge chunks.
- **Repro:** `01_chunk_sizes_and_shapes.py`.

### P2. Daily 4-D variables (one file per year): time chunk doesn't divide the year
- **Which daily variables are affected.** Not every daily file is per-year. The NEP
  daily products use two layouts, and which one a variable gets follows its
  dimensions:
  - **2-D variables, `(time, y, x)`: one file for the whole period.** These are surface
    or bottom fields, 16 in raw and in regrid: `tos`, `tob`, `ssh`, `btm_o2`, `chlos`,
    `phycos`, `pco2surf`, ... One NetCDF covers 1993–2025, so the whole series is one
    virtual array and nothing has to be joined. These are fine.
  - **4-D variables, `(time, z_l, y, x)`: one file per year.** These are depth-resolved
    fields on 52 levels:
    - raw: `dissic`, `no3`, `o2`, `po4`, `si`, `so`, `talk`, `thetao`, `uo`, `vo`,
      `volcello`, `vollcello`
    - regrid: the same without `uo` and `vo`

    Each variable has 33 yearly files (1993 to 2025) that must be joined along time to
    make one series. That is where it breaks. In the newest releases, every daily 4-D
    variable is per-year and every per-year variable is 4-D.
  - The affected files (726) are listed in
    [Appendix 2](#appendix-2-files-affected-by-p2).
- **Evidence:** the per-year files use a time chunk of 100, while each file holds 365 or
  366 days, so every year ends in a partial chunk of 65 or 66 days. HDF5 stores that last
  chunk at full size, padded with the fill value.
- **Why it matters:** a Zarr array has one regular chunk grid, so every chunk except the
  last must be exactly 100 days long. A year's partial last chunk can't sit in the
  middle of the series. The files can't be joined into one virtual array without either
  variable-length chunks or rewriting the files.
- **What the EarthMover build did: left the variables out.** Earthmover's daily store
  (Arraylake `NOAA-PMEL/cefi-nep-hindcast-daily`, groups `raw/main` and `regrid/main`),
  the intended production version and built from r20250912, contains only the 14
  full-period 2-D variables.
  Every per-year variable (`dissic`, `thetao`, `so`, `no3`, `o2`, ...) is missing. Their
  builder skipped those variables because concatenating the yearly files failed
  (earthmover-support/cefi#3), and they were considering variable-length chunks as a way
  around it.
  - What the store does contain is correct: `tos` matched the source NetCDF at six time
    points in both groups.
  - The fact that the production build had to drop the daily 4-D ocean state and
    biogeochemistry is the clearest evidence that P2 blocks real use of the data.
- **Concatenation refuses.** VirtualiZarr's `xr.concat` stops with *"Cannot concatenate
  arrays with partial chunks because only regular chunk grids are currently supported.
  Concat input 0 has array length 365 ... not evenly divisible by chunk length 100."*
- **Appending one year at a time is worse: it runs, but misplaces the data.** Writing
  the first year and then adding each later year with VirtualiZarr's
  `vz.to_icechunk(..., append_dim="time")` runs without error, because the append
  doesn't check chunk alignment the way concatenation does. The data ends up under the
  wrong dates.
- **Repro:** `02a_per_year_time_chunks.py` (concatenation refused) and
  `02b_append_misplaces_data.py` (a two-year append into a throwaway store, compared with
  the source files).

### P3. Bundled `volcello`, and a typo'd `vollcello` series
- **Bundled copies:** a full 4-D `volcello` is stored inside the files of other 4-D
  variables: 62 files in NEP monthly raw and 62 in NWA monthly raw. Two NEP daily raw
  variables also carry one. A naive merge of a product's files sees many `volcello`
  arrays. The copies also inflate file size: NEP monthly `thetao` is 16.5 GB against
  7.4 GB for `volcello` alone.
- **Typo'd series:** NEP daily raw and regrid carry both `volcello` (33 files each) and
  `vollcello` (33 files each). Six daily 4-D files bundle `vollcello` and name it in
  `external_variables`.
- **Repro:** `03_bundled_volcello_and_vollcello.py`.

### P4. Static files: netCDF3 format, masked coordinates, naming
- **Format:** the 10 static files in the raw products (`ocean_static.nc`,
  `ice_static.nc`) are netCDF3 (`CDF\x02`). VirtualiZarr's HDFParser fails on them
  (`file signature not found`), so they need the netCDF3 parser or conversion.
- **Masked coordinates:** their `geolon`/`geolat` are masked over land (57,677 of
  279,072 points in NEP), and each file uses a different fill value: 1e20 in
  `ocean_static`, −1e34 in `ice_static`. The data files carry the full coordinate there
  and are identical elsewhere, so the two conflict in a merge.
- **Naming:** the static files follow no naming pattern. Their JSONs are often misnamed
  or point at another region's static file (P9).
- **Repro:** `04_static_files.py`.

### P5. NWA monthly regrid: two longitude grids
- **Evidence:** `lon` has 774 points in every file of r20250715, but on two grids:
  - from −98.4423 at 0.0807° spacing: 427 files (`Heat_PmE`, `thetao`, ...)
  - from −98.0 at 0.0801° spacing: 37 files (`ALB`, `BMELT`, ...)
- **Why it matters:** this is a genuinely different grid, not a relabel, so the
  37 variables can't share a group with the rest without regridding.
- **Repro:** `05_regrid_lon_grids.py`.

### P6. NWA multi-decadal: one scenario missing a year
- `T_adx` SSP585 has 130 yearly steps and jumps from 2044 to 2046. Every other variable
  and scenario has 131 steps (1970–2100).
- **Repro:** `06_multidecadal_missing_year.py`.

### P7. Decadal forecast: `lead` is encoded as dates
- **Where:** monthly r20250925 and yearly r20250819.
- **Evidence:** `lead` has units `days since <init date>`, and calendar `gregorian`
  where `average_T1` says `proleptic_gregorian`. The numbers differ between inits
  because they follow the calendar (monthly: 15.5, 45.0, ... for 1965; 15.5, 45.5, ...
  for 2020). Decoded, every init's lead becomes a different set of absolute dates.
- **Why it matters:** inits can't be stacked on a shared lead coordinate without
  `decode_times=False` or re-encoding.
- **Repro:** `07_forecast_coordinates.py`.

### P8. Seasonal forecast and reforecast: ensemble and layout
- **Missing member (forecast r20250710):** all 18 init-202510 files have 9 members;
  member 6 is missing. Their chunks change to match: `[12, 9, 200, 200]` in raw,
  `[4, 3, 282, 258]` in regrid.
- **Fill values (reforecast r20250413):** `_FillValue` is 9.97e36 in 90 inits and NaN in
  30, for each of `sos`, `tob` and `tos`. Virtual concatenation needs identical fill
  values.
- **Layout:** forecasts are `(lead, member, y, x)` and reforecasts `(member, lead, y, x)`.
  `lead` has units `months` in forecasts and none in reforecasts. Forecast and reforecast
  therefore can't share a store without reordering.
- **Bundled variables:** each file also carries the variable's anomaly (`tos_anom`
  beside `tos`), and seasonal forecast files a `valid_time`.
- **Repro:** `07_forecast_coordinates.py`.

### P9. Kerchunk JSONs

| Problem | Count |
|---|---:|
| Empty (0-byte) JSON | 176 |
| Named with the first character dropped (`hlos...json` → `chlos...nc`) | 568 |
| **Static-file JSON referencing another region's or experiment's static file** (NEP → PCI or NWA decadal; NWA → NEP) | 22 |
| `all.json` referencing all 480 reforecast files | 2 |
| Reference URL lacks `s3://`; the rest include it | 4,749 |
| NetCDF referenced by no JSON | 142 |

Every sampled pair where the JSON exists and references the right file (246 files)
matched VirtualiZarr's manifest exactly: path, offset and length for every chunk. Small
chunks that Kerchunk inlines as base64 were not compared.

- **Repro:** `08_kerchunk_json_problems.py`.

### Smaller inconsistencies (don't block a build)
- **Extra coordinate variables:** NWA monthly raw bundles the sea-ice grid's `xT`, `yT`,
  `xTe` and `yTe` in 40 files.

## Appendix 2: Files affected by P2

These are the per-year daily 4-D files in the newest NEP daily releases: 726 NetCDFs,
33 per variable (`YYYY01-YYYY12`, 1993–2025).

| Directory | Variables | Files |
|---|---|---:|
| `northeast_pacific/full_domain/hindcast/daily/raw/r20260701/` | `dissic`, `no3`, `o2`, `po4`, `si`, `so`, `talk`, `thetao`, `uo`, `vo`, `volcello`, `vollcello` | 396 |
| `northeast_pacific/full_domain/hindcast/daily/regrid/r20260701/` | `dissic`, `no3`, `o2`, `po4`, `si`, `so`, `talk`, `thetao`, `volcello`, `vollcello` | 330 |

Filename pattern (POSIX extended regular expression, no backreferences, so it works with
GNU grep, ugrep and Python's `re`):

```text
^(dissic|no3|o2|po4|si|so|talk|thetao|uo|vo|volcello|vollcello)\.nep\.full\.hcast\.daily\.(raw|regrid)\.r20260701\.[0-9]{6}-[0-9]{6}\.nc$
```

To list them (anonymous access; `awk` keeps only the file name from `aws s3 ls`):

```bash
P='^(dissic|no3|o2|po4|si|so|talk|thetao|uo|vo|volcello|vollcello)\.nep\.full\.hcast\.daily\.(raw|regrid)\.r20260701\.[0-9]{6}-[0-9]{6}\.nc$'
for grid in raw regrid; do
  aws s3 ls --no-sign-request \
    s3://noaa-oar-cefi-regional-mom6-pds/northeast_pacific/full_domain/hindcast/daily/$grid/r20260701/ \
    | awk '{print $4}' | grep -E "$P"
done
```

This lists 396 raw and 330 regrid files. The pattern matches none of the full-period
2-D files (`...199301-202512.nc`), the static files, or the Kerchunk JSONs.

## Appendix 3: Method and limitations

### Method

The scanners read the whole bucket; `checks.py` then reports on the newest release of
each product (pass `--all-releases` to report on every release directory). Every step
reads metadata only, except a few targeted reads (P2, P4). Nothing reads whole data
variables.

| Step | Script | Output (in `audit/out/`) |
|---|---|---|
| List every object, parse path and filename | `inventory.py` | `inventory.parquet` |
| Read HDF5/netCDF3 metadata and small coordinate values from every NetCDF | `scan_headers.py` | `headers.jsonl` (500 MB, not committed) |
| Summarize every Kerchunk JSON | `scan_kerchunk.py` | `kerchunk.jsonl` (not committed) |
| Flatten to tables | `tables.py` | `files/vars/axes.parquet` (not committed) |
| Parse a sample with VirtualiZarr (one file per distinct variable signature, up to 20 per release; 268 files in the NEP and NWA newest releases) and compare each manifest with its Kerchunk JSON | `smoke_virtualizarr.py` | `smoke.jsonl` (not committed) |
| Read data at duplicated time stamps (none in the newest releases) | `dup_values.py` | – |
| Check Earthmover's daily store, and a throwaway appended store, against the source NetCDFs at single grid points (P2) | `repro/02b_append_misplaces_data.py` (append); manual check (Earthmover) | – |
| Run all checks | `checks.py` | `findings.csv`, `time_axes.csv` (also include the PCI drafts; filter on `group`) |

To rerun, from the repo root:

```bash
/srv/conda/bin/python3.12 -m venv audit/.venv
audit/.venv/bin/pip install -r audit/requirements.txt
audit/.venv/bin/python audit/inventory.py
audit/.venv/bin/python audit/scan_headers.py --workers 6
audit/.venv/bin/python audit/scan_kerchunk.py
audit/.venv/bin/python audit/tables.py
audit/.venv/bin/python audit/smoke_virtualizarr.py --workers 4
audit/.venv/bin/python audit/checks.py
```

Tested with h5py 3.16.0, s3fs 2026.9.0, xarray 2026.7.0, virtualizarr 2.7.3,
obstore 0.11.1, cftime 1.6.5, numpy 2.5.3, pandas 3.0.6, scipy 1.18.1.

On a 4-CPU hub with a 3.9 GB memory cap, the header scan of the whole bucket takes about
45 minutes and the smoke test about 30. More than about 6 workers risks the OOM killer,
which hangs `multiprocessing.Pool`. The scans are resumable: rerun to pick up where they
stopped.

### Limitations

- **Data values** were read only for the cases above. A block of zeroed or missing data
  with valid time stamps would not be detected. A cheap follow-up is to look for
  anomalously small compressed chunks, since zeros compress to almost nothing.
- **The VirtualiZarr parse and Kerchunk byte-range comparison** covered a sample
  (268 NEP and NWA files), not every file. The header checks covered every
  file.
- **Raw vs regrid consistency** (same variables and time axes in both) was not checked.
