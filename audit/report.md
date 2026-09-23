# CEFI regional MOM6 source-file audit

Issue: noaa-nwfsc/cefi-icechunks#5. Audit run 2026-09-23 against
`s3://noaa-oar-cefi-regional-mom6-pds` (anonymous). This report diagnoses only; it
proposes no fixes.

**Goal it serves.** One virtual Icechunk group per region / experiment / frequency /
grid holding every variable (for example `nep/hindcast/regrid`). The question for each
problem is whether it stops a variable from joining that group, or stops a variable's
files from being concatenated.

## Summary

- **The newest releases are much cleaner than r20250912**, the release the current NEP
  builds use. In every newest hindcast release except PCI monthly raw, all variables share
  a single time axis. The 390 vs 396 split, the daily series that end in different months,
  and the zeroed salinity are all confined to NEP **r20250912**, and to **r20251001**,
  which is a byte-for-byte copy of it.
- **What still blocks one group per series in the newest releases:**
  - Per-year daily files use a 100-step time chunk that doesn't divide 365/366, so they
    can't be concatenated on a regular chunk grid (P1).
  - A full 4-D `volcello` is bundled inside other variables' raw files (P6).
  - The static files are netCDF3 and have masked coordinates (P8).
  - NWA monthly regrid mixes three longitude grids (P9).
  - PCI monthly raw has empty and broken files (P10).
  - Forecast `lead` and `member` coordinates are inconsistent (P12, P13).
- **Kerchunk JSON content is sound; the problems are around it.** Where a JSON exists
  and points at the right file, its byte ranges matched VirtualiZarr's manifest in every
  sampled file but two. However:
  - 189 JSONs are empty.
  - 950 are misnamed (a character dropped).
  - 25 static-file JSONs point at **another region's or experiment's** static file (NEP
    r20260701's `ocean_stati.json` references the Pacific Islands `ocean_static.nc`, for
    example). Anyone using them silently gets the wrong grid.
  - 394 more point into a different directory in the same region.
  - 550 NetCDFs are referenced by no JSON at all.
  - Reference URLs mix `s3://` and bare paths.
- **VirtualiZarr parses every HDF5 file sampled** (688 of 688). It fails only on the
  netCDF3 static files (23 sampled, 28 in the bucket).

## Newest release in each series

"Time axes" is the number of distinct time axes among the hindcast variables; 1 means
every variable can share one time dimension. The problem codes refer to the sections
below.

| Series | Release | .nc | Vars | Time axes | Remaining problems |
|---|---|---:|---:|---:|---|
| nep hindcast daily raw | r20260701 | 414 | 28 | 1 | P1, P6 (volcello + vollcello), P8 |
| nep hindcast daily regrid | r20260701 | 346 | 26 | 1 | P1, P6 (vollcello) |
| nep hindcast monthly raw | r20260701 | 463 | 461 | 1 | P6, P8 |
| nep hindcast monthly regrid | r20260701 | 437 | 437 | 1 | none found |
| nwa hindcast daily raw | r20250715 | 13 | 11 | 1 | P8 |
| nwa hindcast daily regrid | r20250715 | 11 | 11 | 1 | none found |
| nwa hindcast monthly raw | r20250715 | 490 | 488 | 1 | P6, P8 |
| nwa hindcast monthly regrid | r20250715 | 464 | 464 | 1 | P9 (two lon grids) |
| nwa multi-decadal yearly raw | r20260331 | 76 | 19 | 2 | P11 |
| nwa multi-decadal yearly regrid | r20260331 | 32 | 8 | 1 | none found |
| nwa decadal forecast monthly raw / regrid | r20250925 | 1100 / 1098 | 18 | – | P12, P8 (raw) |
| nwa decadal forecast yearly raw / regrid | r20250819 | 367 / 366 | 6 | – | P12 |
| nwa seasonal forecast monthly raw / regrid | r20250710 | 73 / 72 | 18 | – | P13 |
| nwa seasonal reforecast monthly raw / regrid | r20250413 | 481 / 480 | 4 | – | P13 (fill values), P8 (raw) |
| pci hindcast daily raw | r20260427 | 19 | 18 | 1 | P14 |
| pci hindcast daily regrid | r20260427 | 16 | 16 | 1 | none found |
| pci hindcast monthly raw | r20260427 | 422 | 421 | 2 | P6, P10, P14, P15 |
| pci hindcast monthly regrid | r20260427 | 336 | 336 | 1 | P10 (`calc` JSON only) |

Kerchunk problems (P16) are listed separately; they affect nearly every release.

## Problems

Each problem lists where it occurs, the evidence, why it matters for a virtual Icechunk,
and the script under `audit/repro/` that reproduces it. Every finding row is in
`audit/out/findings.csv`.

### P1. Per-year daily files: time chunk doesn't divide the file length
- **Where:** NEP daily, every release, raw and regrid (the 3-D variables stored one
  file per year: `dissic`, `no3`, `o2`, `po4`, `si`, `so`, `talk`, `thetao`, `uo`,
  `vo`, `volcello`, `vollcello`, ...). 58 variable series in total.
- **Evidence:** the time chunk is 100 while files hold 365 or 366 steps, so every year
  ends in a partial chunk (65 or 66 steps).
- **Why it matters:** VirtualiZarr refuses to concatenate them: *"Cannot concatenate
  arrays with partial chunks because only regular chunk grids are currently supported.
  Concat input 0 has array length 365 ... not evenly divisible by chunk length 100."*
  This is why the daily 3-D variables can't join the full-period variables. Those are
  single files with a 213-step time chunk, which is fine within one group, since each
  array may have its own chunks.
- **Also:** these chunks are 160 MB uncompressed (`[100, 10, 200, 200]` float32), so
  any read touches 160 MB. The same chunk shape appears in 15–77 variables of every
  NEP and NWA monthly release.
- **Repro:** `03_per_year_time_chunks.py`.

### P2. NEP monthly r20250912: duplicated six-month tail (the 390 vs 396 split)
- **Where:** `nep/hindcast/monthly/{raw,regrid}/r20250912`. 110 raw and 92 regrid
  variables (the 2-D ocean/ice monthly stream) have 396 steps. The other ~360 have 390.
- **Evidence:** the 396-step axis ends
  `2025-05-16, 2025-06-16, 2025-01-16, 2025-02-15, ... 2025-06-16`, so it goes
  backwards once. The six repeated months hold data **identical** to Jan–Jun 2025
  (checked for every affected file: `audit/out/dup_values.csv`). It's a verbatim repeat,
  not different data.
- **Why it matters:** two time axes in one release, which is the reason for the current
  `main`/`aux1` split.
- **Status:** not present in r20260701, where every variable has 396 clean steps
  (1993-01 to 2025-12).
- **Repro:** `04_monthly_duplicated_tail.py`.

### P3. `sisnmass` (NEP monthly r20250912): broken time axis
- **Evidence:** 396 steps, 71 duplicated stamps, and the last stamps are all
  `1993-01-01` (time value 0). Unlike P2, the data at the duplicated stamps differs, so
  this is real data with a broken time coordinate.
- **Repro:** `04_monthly_duplicated_tail.py`.

### P4. Daily salinity `so` (NEP r20250912): zeroed data and zeroed time stamps
- **Where:** `so` 1999 and 2001, daily raw and regrid r20250912 (and the r20251001
  copy).
- **Evidence:** in 1999, step 317 (Nov 14) and steps 321–348 (Nov 18 – Dec 15) hold
  salinity exactly 0.0 over the ocean, and 27 of those steps also have time value 0
  (decodes to 1993-01-01). In 2001, steps 336–364 (Dec 3–31) are zeroed with time
  value 0, and one more step (334) has time 0 but real data. Checked on one 200×200
  surface tile.
- **Why it matters:** the earlier workaround reassigned a clean time axis. That fixes
  the stamps but silently keeps about 29 days a year of zero salinity.
- **Status:** fixed in r20260701 (no zero stamps, no zeroed data).
- **Repro:** `05_salinity_zeroed_days.py` (compares both releases).

### P5. NEP daily r20250912: `chlos`/`phycos` end later and use different chunks
- **Evidence:** 24–26 variables end 2025-06-30, but `chlos` and `phycos` end 2025-08-22
  (11,922 vs 11,869 steps). Their 2025 file is named `202501-202512` but holds
  Jan 1–Aug 22. Their time chunk is 37 in 1993–2024 and 29 in 2025.
- **Status:** r20260701 ends every variable at 2025-12-31.
- **Repro:** `06_daily_series_end_dates.py`.

### P6. Bundled `volcello`, and a typo'd `vollcello` series
- **Bundled copies:** a full 4-D `volcello` is stored inside 62–66 other variables'
  files in every *raw* monthly release (NEP, NWA, PCI) and in some daily ones. A naive
  merge sees several `volcello` arrays. In NEP monthly raw r20250912 they even disagree
  (390 vs 396 steps), as earthmover-support/cefi#4 found. The copies also inflate file
  size; the PCI 4-D raw files are about 43 GB each.
- **Typo'd series:** NEP daily raw and regrid carry both `volcello` (66 files) and
  `vollcello` (66 files). The 4-D daily files bundle `vollcello` and name it in
  `external_variables`.
- **Repro:** `08_bundled_volcello_and_vollcello.py`.

### P7. NEP daily r20251001 is a copy of r20250912, with gaps
- **Evidence:** all 405 NetCDFs are named `r20250912` and have the same ETag as the
  files in r20250912. `chlos` and `phycos` are missing entirely. 2022 is missing for
  `dissic`, `no3`, `o2`, `po4`, `si`, `talk` and `vollcello`, which leaves those series
  365 steps short.
- **Repro:** `07_release_r20251001_is_a_copy.py`.

### P8. Static files: netCDF3 format, and masked coordinates
- **Format:** the 28 `ocean_static.nc` / `ice_static.nc` / `ice_monthly.static.nc`
  files are netCDF3 (`CDF\x01` and `CDF\x02`). VirtualiZarr's HDFParser fails on them
  (`file signature not found`), so they need the netCDF3 parser or conversion.
- **Masked coordinates:** their `geolon`/`geolat` are masked over land (57,677 of
  279,072 points in NEP), and each file uses a different fill value: 1e20 in
  `ocean_static`, −1e34 in `ice_static`. The data files carry the full coordinate
  there, so the two conflict in a merge.
- **Naming:** the static files follow no naming pattern. Their JSONs are often
  misnamed, and 25 point at another region's or experiment's static file (P16).
- **Repro:** `02_netcdf3_static_files.py`.

### P9. NWA monthly regrid: three longitude grids in one release
- **Evidence:** `lon` has 774 points in every file, but in three versions:
  - from −98.4423 at 0.0807 spacing (for example `Heat_PmE`)
  - from −98.0 at 0.0801 spacing (for example `ALB`, `BMELT`, 37 files)
  - in r20230520 only, the first grid again but labelled 0–360 (261.56 onward), in 16
    files (`MLD_003`, `chlos`, ...)
- **Why it matters:** the 0.0801 grid is a genuinely different grid, not a relabel, so
  those variables can't share a group with the rest.
- **Repro:** `09_regrid_lon_conventions.py`.

### P10. PCI monthly raw: empty or broken files, and bad Kerchunk JSONs
- `T_adx_2d`: time has length 0 and no units, the data is `[0, 539, 726]`, and
  `xq`/`yh` are all zeros. Its Kerchunk JSON still describes 396 steps.
- `ffedet_btm`: the data variable is empty (`[0, 539, 725]`), and `xh`/`yh` are all
  zeros.
- `speed`: the file has no `speed` variable at all, and `xh`/`yh` are all zeros.
- `calc` (raw and regrid): its JSON is named `alc...json`. Every chunk reference has the
  right length but an offset shifted by a constant (−9,298 bytes raw, +1,463 regrid),
  and the JSON omits `volcello`. The JSONs are dated later than the NetCDFs, so they
  were generated from a different copy of each file than the one in the bucket.
- **Repro:** `10_pacific_islands_broken_files.py`.

### P11. NWA multi-decadal: one scenario missing a year
- `T_adx` SSP585 has 130 yearly steps and jumps from 2044 to 2046. Every other
  variable and scenario has 131 steps (1970–2100).
- **Repro:** `12_multidecadal_missing_year.py`.

### P12. Decadal forecast: `lead` is encoded as dates
- **Evidence:** `lead` has units `days since <init date>`, and calendar `gregorian`
  where `average_T1` says `proleptic_gregorian`. Decoded, every init's lead becomes
  a different set of absolute dates, so inits can't be stacked on a shared lead
  coordinate without `decode_times=False` or re-encoding. In the yearly files the raw
  numbers differ between inits as well.
- **Dimension order changed between releases:** `(lead, member, y, x)` in r20250502,
  `(member, lead, y, x)` in r20250925.
- **Repro:** `11_seasonal_forecast_members.py` (the last lines compare decadal and
  seasonal `lead`).

### P13. Seasonal forecast / reforecast: ensemble and layout inconsistencies
- **Member order:** in r20250413 forecasts, `member` is out of order
  (`1,2,3,4,6,7,8,9,10,5`).
- **Missing member:** in r20250710, all 18 init-202510 files have 9 members (member 6
  missing). Chunks change to match: `[12, 9, 200, 200]` in raw, `[4, 3, 282, 258]` in
  regrid.
- **Fill values:** in r20250413 reforecasts, `_FillValue` is 9.97e36 in 90 inits and
  NaN in 30 of `sos`/`tob`/`tos`. Virtual concatenation needs identical fill values.
- **Uneven inits:** in r20250413 forecasts, `sob` has one init while the other
  variables have two.
- **Layout differences (not defects in themselves):**
  - Forecasts are `(lead, member, ...)` and reforecasts `(member, lead, ...)`.
  - `lead` has units `months` in some releases and none in others.
  - Reforecast init months are Feb/Jun/Sep/Dec in r20250212 and Jan/Apr/Jul/Oct in
    r20250413.
- **Repro:** `11_seasonal_forecast_members.py`.

### P14. Chunks longer than the array
- **Where:** PCI monthly raw, all 422 files: `average_DT` chunk `[512]` and `time_bnds`
  chunk `[800, 2]` on a 396-step axis. The same happens in a few NWA/PCI static files
  (`time` `[1]` with chunk `[512]`).
- **Why it matters:** VirtualiZarr reads these but won't concatenate them ("chunk shape
  larger than their array shape"). That only matters when appending new time steps,
  because these are full-period files.

### P15. PCI raw: small chunks make indexing slow
- **Evidence:** PCI raw uses `[20, 100, 100]` (0.8 MB) for 2-D and `[10, 10, 50, 50]`
  (1 MB) for 4-D variables. The monthly raw release totals about 3.3 million chunks
  across its main variables.
- **Why it matters:** VirtualiZarr needed 4–8 minutes per 4-D file to index it
  (variable plus bundled `volcello`), against about 6 s for a 2-D file. That's many
  hours for a full build.

### P16. Kerchunk JSONs

| Problem | JSONs / NetCDFs |
|---|---:|
| Empty (0-byte) JSON | 189 |
| Named with the first character dropped (`hlos...json` → `chlos...nc`) | 947 |
| Named with the last character dropped (`ocean_stati.json`) | 3 |
| **References another region's or experiment's static file** (NEP → PCI or NWA; NWA → NEP) | 25 |
| References a NetCDF in another directory of the same region (r20251001 → r20250912: 386; daily static → monthly: 8) | 394 |
| `all.json` referencing 360–480 files | 4 |
| Reference URL lacks `s3://` (8,543); the rest include it | 8,543 |
| NetCDF referenced by no JSON anywhere | 550 |
| JSON disagrees with its NetCDF (`calc`, `T_adx_2d`; P10) | 2 files |

For every other sampled pair (658 files with a JSON), every chunk reference in the JSON
matched VirtualiZarr's manifest exactly: path, offset and length. Small chunks that
Kerchunk inlines as base64 were not compared.

- **Repro:** `01_kerchunk_json_problems.py`.

### Smaller inconsistencies (don't block a build)
- **Time units:** some files write `days since 1993-01-01` and others
  `... 00:00:00`, which are equivalent. NWA r20230520 mixes reference years 1980 and
  1993.
- **Chunk shapes vary between variables** in the same group (for example 4 MB 2-D vs
  160 MB 3-D in NEP monthly raw). That's allowed within one Zarr group, and it's listed
  here only because the 160 MB chunks are large for readers.

## Checked and found consistent

- **Codecs and dtype:** across all 13,269 HDF5 files, every main variable is float32
  with zlib level 2. 12,831 also use shuffle and 438 don't, but never mixed within one
  release directory, so codecs never block a merge.
- No HDF5 file failed to open; no file uses HDF5 subgroups.
- In the newest hindcast releases, time units and calendar agree within each group, and
  grid coordinates (`xh`, `yh`, `lat`, `lon`, `z_l`, ...) agree across files, apart
  from the cases above.
- The decadal forecasts have a complete annual init series (1965–2025 in r20250925).

## Method

Every step reads metadata only, except the targeted reads in P2–P4 and P10. Nothing
reads whole data variables.

| Step | Script | Output (in `audit/out/`) |
|---|---|---|
| List every object, parse path and filename | `inventory.py` | `inventory.parquet` |
| Read HDF5/netCDF3 metadata and small coordinate values from all 13,307 NetCDFs | `scan_headers.py` | `headers.jsonl` (500 MB, not committed) |
| Summarize all 13,399 Kerchunk JSONs | `scan_kerchunk.py` | `kerchunk.jsonl` (not committed) |
| Flatten to tables | `tables.py` | `files/vars/axes.parquet` (not committed) |
| Parse a sample with VirtualiZarr (one file per distinct variable signature, topped up to 20 per release: 699 files, plus 12 from an earlier unsampled pass) and compare each manifest with its Kerchunk JSON | `smoke_virtualizarr.py` | `smoke.jsonl` (not committed) |
| Read data at duplicated time stamps | `dup_values.py` | `dup_values.csv` |
| Run all checks | `checks.py` | `findings.csv`, `time_axes.csv` |

To rerun, from the repo root:

```bash
/srv/conda/bin/python3.12 -m venv audit/.venv
audit/.venv/bin/pip install -r audit/requirements.txt
audit/.venv/bin/python audit/inventory.py
audit/.venv/bin/python audit/scan_headers.py --workers 6
audit/.venv/bin/python audit/scan_kerchunk.py
audit/.venv/bin/python audit/tables.py
audit/.venv/bin/python audit/smoke_virtualizarr.py --workers 4
audit/.venv/bin/python audit/dup_values.py
audit/.venv/bin/python audit/checks.py
```

Tested with h5py 3.16.0, s3fs 2026.9.0, xarray 2026.7.0, virtualizarr 2.7.3,
obstore 0.11.1, cftime 1.6.5, numpy 2.5.3, pandas 3.0.6, scipy 1.18.1.

On a 4-CPU hub with a 3.9 GB memory cap, the header scan takes about 45 minutes and the
smoke test about 30. More than about 6 workers risks the OOM killer, which hangs
`multiprocessing.Pool`. The scans are resumable: rerun to pick up where they stopped.

## Limitations

- **Data values** were read only where time stamps repeat and in the cases above. A
  zeroed block with *valid* time stamps (like two of the `so` 1999 steps) would not be
  detected elsewhere. A cheap follow-up is to look for anomalously small compressed
  chunks, since zeros compress to almost nothing.
- **The VirtualiZarr parse and Kerchunk byte-range comparison** covered a 711-file
  sample, not all 13,307 files. The header checks covered every file.
- **Raw vs regrid consistency** (same variables and time axes in both) and
  **consistency across releases** (beyond duplication) were not checked.
