# Rebuilding the CEFI NetCDFs: draft standard and effort

Companion to [`report.md`](report.md), which lists the problems (P1–P17). This document
covers what a rebuild would fix and what it can't, a **draft** standard for the rebuilt
files, and what the work would take. The standard is a starting point for discussion
with CEFI, not a settled spec. The numbers come from the audit and from timings on real
files, stated below.

## Summary

- **Machine time is small.** Rewriting the newest release of every series (18.9 TB
  compressed, about 40 TB uncompressed) is roughly **250–1,000 CPU core-hours**. On a
  fleet of about 25 VMs that is **under a day of wall-clock time**, including
  validation, for about **$30–100 of compute**.
- **The real cost is people and agreement.** Agreeing a standard with CEFI, writing and
  testing the pipeline, and piloting it is several weeks. Allow **about 3–4 weeks of
  engineering once the standard is agreed**, plus CEFI's own calendar for problems that
  need their model output.
- **Most problems can be fixed by reprocessing the published files.** A handful can't:
  empty or broken files, a missing ensemble member, a missing year, and variables
  regridded to a different longitude grid need CEFI to regenerate from model output.

## What a rebuild can and can't fix

"Reprocess" means anyone with read access (you, with VMs) can fix it by rewriting the
newest published files. "CEFI" means the data needed isn't in the bucket.

| Problem | Fix | Who |
|---|---|---|
| P17 chunk sizes and shapes; P1 per-year time chunks; P14 oversized chunks; P15 slow indexing | Rewrite with standard chunks | Reprocess |
| P6 bundled `volcello`, typo'd `vollcello` | Drop bundled copies; keep one `volcello` (static or its own file) | Reprocess |
| P8 netCDF3 static files, masked `geolon`/`geolat` | Rewrite as netCDF4; take coordinates from the data files | Reprocess |
| P12 decadal `lead` as dates; P13 member order, fill values, dimension order | Re-encode `lead` as months since init; sort `member`; one fill value; one dimension order | Reprocess |
| Dimension names (`jh/ih` vs `yh/xh`), time units spelling, file naming | Normalize metadata and names | Reprocess |
| P2–P5, P7 (NEP r20250912 / r20251001 time axes, zeroed `so`) | Use the newest release (r20260701), which doesn't have them; retire r20251001 | Reprocess / CEFI decision |
| P9 NWA regrid variables on the 0.0801° grid | Re-regrid from raw onto the common grid (needs CEFI's regridding weights and method) | CEFI (or reprocess, with their weights) |
| P10 PCI `T_adx_2d`, `ffedet_btm`, `speed` empty or broken | Regenerate from model output | **CEFI** |
| P13 member 6 missing from seasonal forecast init 202510 | Regenerate | **CEFI** |
| P11 `T_adx` SSP585 missing 2045 | Regenerate | **CEFI** |
| P16 Kerchunk JSONs | Regenerate from rebuilt files, or retire the JSON workflow | CEFI decision |

## Draft standard (v0, for discussion)

### Principles

1. **One chunking rule per kind of variable, applied everywhere**: every region,
   release, raw and regrid. No netCDF-C default chunking.
2. **Chunks are 4–50 MB uncompressed** (roughly 1–20 MB compressed), inside the
   1–100 MB range usually recommended for cloud object storage.
3. **Each chunk covers the whole horizontal domain.** One 2-D field is only 1.1 MB (NEP),
   1.6 MB (PCI) or 2.6 MB (NWA) as float32, so splitting the domain into tiles only
   creates ragged edge chunks and more requests.
4. **The time chunk divides every file's length exactly**, so files can be concatenated
   and appended on a regular chunk grid (P1). A single full-period file may end in a
   partial chunk only if it will never be extended.
5. **Chunks never exceed the array length** (P14), and bounds variables (`time_bnds`)
   are chunked like their axis.

### Proposed chunk shapes

Sizes are float32, uncompressed, for the raw grids (regrid grids are one row and column
smaller and nearly identical).

| Variable kind | Chunk | NEP (816×342) | PCI (539×725) | NWA (845×775) |
|---|---|---:|---:|---:|
| Monthly 2-D `(time, y, x)` | `(12, Y, X)` | 13 MB | 19 MB | 31 MB |
| Monthly 3-D `(time, z_l=52, y, x)` | `(1, 13, Y, X)` | 15 MB | 20 MB | 34 MB |
| 3-D on interfaces `(time, z_i=76, y, x)` | `(1, 19, Y, X)` | 21 MB | 30 MB | 50 MB |
| Daily 2-D | `(1, Y, X)` | 1.1 MB | 1.6 MB | 2.6 MB |
| Daily 3-D | `(1, 13, Y, X)` | 15 MB | 20 MB | 34 MB |
| Forecast `(member, lead, y, x)` | `(all members, 1, Y, X)` | – | – | 26 MB (10 members) |
| Yearly / multi-decadal 2-D | `(10, Y, X)` | – | – | 26 MB |

Why these:
- **Monthly 2-D:** 12 divides 396 (33 years) and every whole-year append.
- **Daily:** the time chunk must be **1**, because 1 is the only chunk that divides
  both 365 and 366 (P1). That makes daily 2-D chunks small (1–2.6 MB) but regular.
  The alternative is full-period daily files with a larger time chunk, which can't be
  extended without rewriting them. That's a decision for CEFI (see open questions).
- **3-D:** 13 divides 52 levels and 19 divides 76.

**Trade-off to state openly.** These chunks favor maps and profiles (one time step,
the whole domain). A single-point time series over 33 years touches every chunk of the
variable. No one chunking serves both. If point time series matter, the usual answer is
a separate time-series-optimized copy (a materialized Zarr), not a compromise chunking
that serves neither well.

### Encoding and metadata

- **Format:** netCDF4/HDF5 everywhere, including the static files.
- **Codec:** zlib level 2 with shuffle, as now. In a timing test, level 4 made files
  only 2% smaller for about 10% more CPU. zstd would need plugins many readers lack.
- **dtype and fill value:** float32 and one `_FillValue` convention per variable across
  all files (P13 found NaN in some files, 9.97e36 in others).
- **Time:** `days since 1993-01-01 00:00:00`, one calendar (`gregorian`/`standard`),
  mid-period stamps, and `time_bnds` present and chunked like `time`.
- **Coordinates:** one set per region and grid, identical in every file. Unmasked
  `geolon`/`geolat`. One longitude convention for regrid (P9). One dimension naming
  (`yh/xh` or `jh/ih`, not both).
- **Content:** one data variable per file. No bundled `volcello` or other cell
  measures; those live once, in the static file.
- **Forecasts:** dimension order `(member, lead, y, x)` everywhere. `lead` as integers
  with `units = "months"` (or days), never dates relative to the init. `member` sorted
  and complete. `init` stored as a coordinate so files stack along it.
- **Names:** one filename pattern for every file, statics included. Variable names
  checked against a list (no `vollcello`).

### Acceptance test

The audit already encodes most of the standard. Run `audit/scan_headers.py`,
`tables.py` and `checks.py` on the rebuilt files; a release passes when `findings.csv`
has no `single-group`, `concat`, `chunking` or `file` rows. That takes about 45 minutes
on a small hub for the whole bucket, and parallelizes trivially.

### Open questions for CEFI

1. **File granularity:** one file per variable per year (appendable, many more files:
   about 15,000 for NEP monthly raw alone), or one file per variable for the full
   period (fewer files, rewritten whenever the period is extended)?
2. **Daily 2-D chunks:** accept 1–2.6 MB chunks (time chunk 1), or use full-period
   files with a larger time chunk?
3. **Which releases to rebuild:** only the newest in each series (18.9 TB), or all
   (37 TB)? Retire r20251001, which is a copy of r20250912?
4. **Longitude convention** for regrid (−180..180 or 0..360).
5. **Kerchunk JSONs:** regenerate, or retire in favor of virtual Icechunk stores?

## Effort

### Data volume

| Scope | Files | Compressed | Main variables uncompressed | Bundled `volcello` (dropped) |
|---|---:|---:|---:|---:|
| Newest release per series (22 series) | 7,576 | 18.9 TB | 40 TB | 12 TB |
| All releases (46 directories) | 13,307 | 37.0 TB | 81 TB | 26 TB |

The largest single file is 43 GB (PCI monthly raw 4-D). Newest-release volume by series
is in the audit's `inventory.parquet` and `vars.parquet`. Most of it is NEP daily raw
(5.3 TB), PCI monthly raw (3.0 TB), NWA monthly raw (2.2 TB) and NWA decadal (2.8 TB).

### Measured throughput

Measured on this JupyterHub, one core, using the audit's clean environment
(h5py 3.16, zlib level 2 + shuffle), on real files:

| Step | Rate | File |
|---|---:|---|
| Decompress (local) | 217–255 MB/s | NEP `tos` 2-D; PCI `rsdo` 4-D |
| Rechunk and compress (local, standard chunks) | 55–61 MB/s | same |
| End to end per core | about 45 MB/s of uncompressed data | |
| Download, one stream, hub → us-east-1 | 68 MB/s | NEP `tos`, 213 MB |
| Read through 1 MB source chunks over the network | **8 MB/s** | PCI `rsdo` |

Both rewrites were lossless, with output about the same size as the source. The last
row shows **the pipeline must copy each whole file to local disk first** and rechunk
locally. Reading through small source chunks over the network is 30× slower.

### Estimate

- **CPU:** 40 TB ÷ 45 MB/s per core ≈ **250 core-hours** at the measured rate. Plan for
  2–4× that for 3-D reshuffling, netCDF4/CF metadata writing, a validation read of every
  output, and reruns: **roughly 500–1,000 core-hours**.
- **Network:** read about 15–19 TB (bundled `volcello` needn't be read) and write about
  15–19 TB. Run the fleet in **us-east-1**, where the bucket is, so transfer is fast and
  free. An in-region VM with 25 Gbit/s networking typically moves 1–2 GB/s to and from S3
  with parallel transfers. That's an assumption, not measured here, because this hub
  isn't in us-east-1.
- **Memory:** rechunking reads one source time-block at a time. The worst case is NWA
  monthly 3-D with source chunks 100 steps long: 100 × 52 × 845 × 775 × 4 bytes = 13.6 GB.
  Allow **16 GB per concurrent 3-D worker**; 2-D workers need about 1 GB.
- **Disk:** local NVMe of about 2× the largest file per concurrent worker (source copy
  plus output): about 100 GB per worker for PCI, much less elsewhere.
- **Example fleet:** 25 VMs × 32 vCPU / 128 GB RAM / 1 TB NVMe (for example
  c6id/m6id.8xlarge class) = 800 cores.
  - CPU: 250–1,000 core-hours ÷ 800 cores ≈ **0.3–1.3 hours**.
  - Transfer: about 35 TB ÷ 25 VMs ≈ 1.4 TB per VM ≈ **0.5–1 hour** at 1 GB/s.
  - Validation scan and Icechunk indexing of the new files: 1–2 hours.
  - **Total: about half a day of wall-clock time**, most of it orchestration slack.
  Scale up or down linearly; the work is embarrassingly parallel (one variable
  file at a time).
- **Cost (rough, on-demand):** compute ~1,000 vCPU-hours at $0.04–0.10 ≈ **$40–100**;
  in-region transfer free; storing ~15–19 TB of output ≈ **$350–450 per month** in S3
  Standard until it replaces the current files. All releases would double compute and
  storage.
- **After the rebuild, the Icechunk build gets much faster.** Standard chunks mean far
  fewer chunk references: the PCI 4-D files that took VirtualiZarr 4–8 minutes each have
  about 80,000 chunks now and would have a few hundred.

### People-time and sequence

| Step | Effort | Notes |
|---|---|---|
| 1. Agree the standard with CEFI | CEFI's calendar | The open questions above |
| 2. Write the rebuild pipeline | 1–2 weeks, one engineer | Copy locally, rechunk, normalize metadata, per-kind rules, forecast handling, idempotent and resumable |
| 3. Turn the audit into pass/fail acceptance tests | 2–3 days | Mostly done: `checks.py` categories |
| 4. Pilot one series end to end | 1–2 days | NEP monthly regrid r20260701 (437 files, 0.33 TB), then build its Icechunk store and test it with users |
| 5. Full run on the fleet | about 1 day | Half a day of machine time, plus reruns |
| 6. Build Icechunk stores from rebuilt files | 1–2 days | One group per series becomes possible |
| 7. CEFI regenerates what reprocessing can't fix | CEFI's calendar | P9 (unless weights shared), P10, P11, missing member |

**Total: about 3–4 weeks of engineering after the standard is agreed.** Machine time
is not the bottleneck.

### Where the output goes

Neither you nor Claude can write to the NODD bucket. Rebuilt files would be staged in a
bucket you control in us-east-1, validated there, and published by CEFI/NODD (or served
from your bucket if CEFI prefers). Icechunk stores can point at either location.

## Assumptions and limits

- Throughput was measured on one core with two files, one 2-D and one 4-D. The 3-D NEP
  and NWA variables weren't timed because a full time-block of them doesn't fit in this
  hub's 3.9 GB memory. The 2–4× planning factor covers this.
- VM network throughput and prices are typical published figures, not measured.
- The estimate covers rewriting the published files. It doesn't cover CEFI rerunning
  model post-processing for the items that need it.
- Output size was about equal to input in both tests. Dropping bundled `volcello`
  (about 12 TB uncompressed in the newest releases) should shrink the raw series
  noticeably.
