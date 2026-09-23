# CEFI regional MOM6 source-file audit

Issue: noaa-nwfsc/cefi-icechunks#5. Audit run 2026-09-23 against
`s3://noaa-oar-cefi-regional-mom6-pds` (anonymous).

**Scope.** The newest release of each product (region / experiment / frequency / grid).
The main report covers the 18 Northeast Pacific (NEP) and Northwest Atlantic (NWA)
products: 6,783 NetCDFs (15.3 TB) and 6,880 Kerchunk JSONs. The four Pacific Islands
(PCI) products are still drafts, so their problems are listed separately at the end
([Pacific Islands draft products](#pacific-islands-draft-products)). They are recorded
for the record, not measured against a finished-product standard. Earlier releases are
superseded and not covered.

**Goal it serves.** One virtual Icechunk group per product holding every variable (for
example `nep/hindcast/monthly/regrid`). For each problem the question is whether it
stops a variable from joining that group, or stops a variable's files from being
concatenated. This report diagnoses only. A draft standard for rebuilt files and an
estimate of the rebuild effort are in [`rebuild.md`](rebuild.md).

## Summary

- **The time axes are in good shape.** Every NEP and NWA hindcast product has a single
  time axis shared by all its variables. No duplicated or backwards time stamps were
  found.
- **There is no chunking standard, and that is the biggest problem.** The main variables
  use 19 different chunk shapes. 406 files use netCDF-C's automatic ~4 MiB chunking,
  meaning no chunking was chosen. The 3-D variables use 160 MB chunks (P1).
- **What else blocks one group per product:**
  - Per-year daily files use a 100-step time chunk that doesn't divide 365/366, so they
    can't be joined on a regular chunk grid. **Earthmover's production daily store leaves
    every per-year variable out for this reason** (the daily 3-D ocean state and
    biogeochemistry). Appending them one year at a time instead runs without error but
    misplaces the data (P2).
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

## Status of each product

"Time axes" is the number of distinct time axes among a hindcast product's variables;
1 means every variable can share one time dimension. Problem codes refer to the sections
below. Kerchunk problems (P9) affect nearly every product and aren't repeated here.

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

## Problems

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
- **Too large (NEP and NWA 3-D).** `[100, 10, 200, 200]` is 160 MB uncompressed. NEP
  monthly `thetao` chunks are 27 MB compressed at the median and up to 94 MB; NWA regrid
  `thetao` is 16 MB median, up to 84 MB. Reading one time step at one level pulls the
  whole chunk.
- **Chunks that don't fit the data.** Time chunks of 100 don't align with years or
  months (P2). Spatial tiles of 200 don't divide the grids (816 × 342, 845 × 775), so
  every file has ragged edge chunks.
- **Repro:** `01_chunk_sizes_and_shapes.py`.

### P2. Per-year daily files: time chunk doesn't divide the file length
- **Which daily variables are affected.** NEP daily variables come in two layouts, and
  only one of them is a problem:
  - **Single full-period file** (16 variables in raw and in regrid: `tos`, `tob`, `ssh`,
    `btm_o2`, `chlos`, `phycos`, ...): one NetCDF covers 1993–2025, so the whole series
    is one virtual array and nothing has to be joined. These are fine.
  - **One file per year** (the 3-D variables: `dissic`, `no3`, `o2`, `po4`, `si`, `so`,
    `talk`, `thetao`, `uo`, `vo`, `volcello`, `vollcello` in raw; the same without `uo`
    and `vo` in regrid): the 33 yearly files have to be joined along time to make one
    series. That is where it breaks.
- **Evidence:** the per-year files use a time chunk of 100, while each file holds 365 or
  366 days, so every year ends in a partial chunk of 65 or 66 days. HDF5 stores that last
  chunk at full size, padded with the fill value.
- **Why it matters:** a Zarr array has one regular chunk grid, so every chunk except the
  last must be exactly 100 days long. A year's partial last chunk can't sit in the
  middle of the series. The files can't be joined into one virtual array without either
  variable-length chunks or rewriting the files.
- **What the professional build did: left the variables out.** Earthmover's daily store
  (Arraylake `NOAA-PMEL/cefi-nep-hindcast-daily`, groups `raw/main` and `regrid/main`),
  the intended production version and built from r20250912, contains only the 14
  full-period 2-D variables.
  Every per-year variable (`dissic`, `thetao`, `so`, `no3`, `o2`, ...) is missing. Their
  builder skipped those variables because concatenating the yearly files failed
  (earthmover-support/cefi#3), and they were considering variable-length chunks as a way
  around it.
  - What the store does contain is correct: `tos` matched the source NetCDF at six time
    points in both groups.
  - The fact that the production build had to drop the daily 3-D ocean state and
    biogeochemistry is the clearest evidence that P2 blocks real use of the data.
- **Concatenation refuses.** VirtualiZarr's `xr.concat` stops with *"Cannot concatenate
  arrays with partial chunks because only regular chunk grids are currently supported.
  Concat input 0 has array length 365 ... not evenly divisible by chunk length 100."*
- **Appending one year at a time is worse: it runs, but misplaces the data.** Writing
  the first year and then adding each later year with VirtualiZarr's
  `vz.to_icechunk(..., append_dim="time")` gives no error, because the append doesn't
  check chunk alignment the way concatenation does.
  - **Where each year lands:** each appended year is written starting at chunk slot
    `floor(days written so far ÷ 100)`, not at its own position. With two years of
    r20260701 files, 1994's first chunk lands at index 300, which the (correct) time
    coordinate labels 1993-10-28. It overwrites the last 65 days of 1993.
  - **After it:** all of 1994 then sits 65 days early, and the last 65 time steps are
    empty.
  - **Over a full 1993–2024 series** the offsets would vary from year to year:
    - every year after 1993 labelled 0–96 days early
    - 11 year boundaries overwriting about 717 days of data in total
    - 20 boundaries exposing about 695 rows of HDF5's padded edge chunks under ordinary
      dates
  - **How it shows up:** only as an "inconsistent chunks" error from `ds.chunks`. The
    dataset otherwise opens and reads without complaint.
- **Repro:** `02a_per_year_time_chunks.py` (concatenation refused) and
  `02b_append_misplaces_data.py` (a two-year append into a throwaway store, compared with
  the source files).

### P3. Bundled `volcello`, and a typo'd `vollcello` series
- **Bundled copies:** a full 4-D `volcello` is stored inside the files of other 3-D
  variables: 62 files in NEP monthly raw and 62 in NWA monthly raw. Two NEP daily raw
  variables also carry one. A naive merge of a product's files sees many `volcello`
  arrays. The copies also inflate file size: NEP monthly `thetao` is 16.5 GB against
  7.4 GB for `volcello` alone.
- **Typo'd series:** NEP daily raw and regrid carry both `volcello` (33 files each) and
  `vollcello` (33 files each). Six daily 3-D files bundle `vollcello` and name it in
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

## Checked and found consistent

- **Time:** within each hindcast product, time units and calendar agree, and there are
  no duplicated, backwards or irregular time stamps (apart from P6).
- **Codecs and dtype:** every main variable is float32 with zlib level 2 and shuffle.
- **Files:** no HDF5 file failed to open, and none uses HDF5 subgroups.
- **Coordinates:** grid coordinates (`xh`, `yh`, `lat`, `lon`, `z_l`, ...) agree across
  a product's files, apart from P4, P5 and P8.
- **Decadal forecasts:** complete annual init series (1965–2025 in r20250925).

## Pacific Islands draft products

The four PCI products (r20260427: hindcast daily and monthly, raw and regrid; 793
NetCDFs, 3.5 TB) are still drafts. The problems below are listed so they're on record as
the products are finished, not as failures against a finished-product standard.

| Product | .nc | Vars | Time axes | Notes |
|---|---:|---:|---:|---|
| pci hindcast daily raw | 19 | 18 | 1 | PCI-1, PCI-3 (static file) |
| pci hindcast daily regrid | 16 | 16 | 1 | none found |
| pci hindcast monthly raw | 422 | 421 | 2 | PCI-1 to PCI-5 |
| pci hindcast monthly regrid | 336 | 336 | 1 | PCI-5 (`calc` JSON) |

### PCI-1. Chunks are very small in raw, and differ from regrid
Measured on actual chunk references:

| Files | Chunk | Uncompressed | Compressed median (10–90%) | Chunks per file |
|---|---|---:|---:|---:|
| PCI monthly raw 2-D | `[20, 100, 100]` | 0.8 MB | 686 KB (158–715 KB) | 960 |
| PCI monthly raw 4-D (`rsdo`) | `[10, 10, 50, 50]` | 1.0 MB | 501 KB (4–865 KB) | 52,800 |
| PCI daily raw 2-D | `[20, 100, 100]` | 0.8 MB | 597 KB (145–651 KB) | 28,944 |
| PCI monthly regrid 2-D | `[100, 200, 200]` | 16 MB | 8.1 MB (3.6–10.8 MB) | 48 |

- One map of a 4-D raw variable through time takes tens of thousands of requests, many
  for a few KB (land or deep levels). The regrid files are chunked 20× larger.
- Small chunks also make building a store slow: VirtualiZarr needed 4–8 minutes to index
  each 4-D raw file, against about 6 s for a 2-D file.
- PCI raw omits the shuffle filter that every other product uses. That doesn't block a
  merge within PCI.
- **Repro:** `01_chunk_sizes_and_shapes.py` (the PCI rows).

### PCI-2. Empty or broken files (monthly raw)
- **`T_adx_2d`:** time has length 0 and no units, the data is `[0, 539, 726]`, and
  `xq`/`yh` are all zeros.
- **`ffedet_btm`:** the data variable is empty (`[0, 539, 725]`), and `xh`/`yh` are all
  zeros.
- **`speed`:** the file has no `speed` variable at all, and `xh`/`yh` are all zeros.

These give monthly raw its second time axis (the empty one).

- **Repro:** `09_pacific_islands_draft.py`.

### PCI-3. Chunks longer than the array
- On the 396-step axis of the monthly raw files, `time_bnds` has chunk `[800, 2]` in 418
  of the 422 files, and `average_DT` has chunk `[512]` in 406. The static files have
  `time` of length 1 with chunk `[512]` (monthly and daily raw).
- VirtualiZarr reads these but won't concatenate them ("chunk shape larger than their
  array shape"). That matters only when appending new time steps.
- **Repro:** `09_pacific_islands_draft.py`.

### PCI-4. Bundled `volcello`
- A full 4-D `volcello` is inside 66 other monthly raw files, making each 4-D raw file
  about 42 GB.
- **Repro:** `03_bundled_volcello_and_vollcello.py` (the `calc` line).

### PCI-5. Kerchunk JSONs
- **Misnamed:** 74 JSONs have the first character dropped (`alc...json` for `calc`) and
  one the last (`ocean_stati.json`).
- **Other directory:** the daily raw static JSON references the monthly raw static file.
- **No JSON:** 4 NetCDFs aren't referenced by any JSON.
- **No `s3://`:** none of the 790 JSONs includes the `s3://` prefix.
- **Disagrees with the NetCDF:**
  - `calc` (raw and regrid): every chunk reference has the right length, but the offset
    is shifted by a constant (9,298 bytes too low in raw, 1,463 too high in regrid). The
    JSON also omits the bundled `volcello`. The JSONs are dated later than the NetCDFs,
    so they were generated from a different copy of each file.
  - `T_adx_2d`: the JSON describes 396 time steps, but the NetCDF has none.
- All other sampled PCI JSONs (71 files) matched VirtualiZarr exactly.
- **Repro:** `09_pacific_islands_draft.py`.

## Method

The scanners read the whole bucket; `checks.py` then reports on the newest release of
each product (pass `--all-releases` to report on every release directory). Every step
reads metadata only, except a few targeted reads (P4, PCI-2). Nothing reads whole data
variables.

| Step | Script | Output (in `audit/out/`) |
|---|---|---|
| List every object, parse path and filename | `inventory.py` | `inventory.parquet` |
| Read HDF5/netCDF3 metadata and small coordinate values from every NetCDF | `scan_headers.py` | `headers.jsonl` (500 MB, not committed) |
| Summarize every Kerchunk JSON | `scan_kerchunk.py` | `kerchunk.jsonl` (not committed) |
| Flatten to tables | `tables.py` | `files/vars/axes.parquet` (not committed) |
| Parse a sample with VirtualiZarr (one file per distinct variable signature, up to 20 per release; 343 files in the newest releases, 75 of them PCI) and compare each manifest with its Kerchunk JSON | `smoke_virtualizarr.py` | `smoke.jsonl` (not committed) |
| Read data at duplicated time stamps (none in the newest releases) | `dup_values.py` | – |
| Check Earthmover's daily store, and a throwaway appended store, against the source NetCDFs at single grid points (P2) | `repro/02b_append_misplaces_data.py` (append); manual check (Earthmover) | – |
| Run all checks | `checks.py` | `findings.csv`, `time_axes.csv` (PCI included; filter on `group`) |

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

## Limitations

- **Data values** were read only for the cases above. A block of zeroed or missing data
  with valid time stamps would not be detected. A cheap follow-up is to look for
  anomalously small compressed chunks, since zeros compress to almost nothing.
- **The VirtualiZarr parse and Kerchunk byte-range comparison** covered a sample
  (268 NEP/NWA files and 75 PCI files), not every file. The header checks covered every
  file.
- **Raw vs regrid consistency** (same variables and time axes in both) was not checked.
