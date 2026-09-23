# CEFI source-file problems (audit, issue #5)

The full catalogue is `audit/report.md`. Every finding is in `audit/out/findings.csv`,
and each problem has a standalone script in `audit/repro/`. This note records what a
later session needs and could not easily reconstruct.

## Scope

The report covers only the **newest release of each of the 22 products**, at the user's
request: older releases are superseded and the CEFI team is fixing things. `checks.py`
defaults to the newest releases; `--all-releases` restores the full view. Problems seen
only in old releases (NEP r20250912: the 390/396 duplicated tail, zeroed salinity,
mismatched daily end dates; r20251001, a byte-identical copy of r20250912) are dropped
from the report. The existing `build_nep_icechunk_*.py` scripts and the README still
point at r20250912, so rebuild them from r20260701.

**Pacific Islands (PCI) products are drafts.** At the user's request their problems are
listed in a separate final section of the report (PCI-1 to PCI-5), not in the main
P1–P9 list, so the report doesn't imply draft products should meet the standard yet.
Keep that framing in anything written for CEFI.

`audit/report-cefi.md` is the user's trimmed, CEFI-facing version. They merged in the
rebuild summary and dropped the PCI section and repo links. Prefer editing that file for
anything going to CEFI; `report.md` is the full internal record.

## Headline (newest releases)

- Time axes are clean: one axis per NEP/NWA hindcast product.
- **Chunking is the biggest problem (P1):** 19 chunk shapes among the NEP/NWA main
  variables, 406 files on netCDF-C default ~4 MiB chunking, and 160 MB 3-D chunks.
  (PCI raw has the opposite problem, ~1 MB chunks: PCI-1.)
- Other blockers:
  - per-year daily files whose 100-step time chunk doesn't divide 365 (P2)
  - bundled `volcello` and the typo'd `vollcello` (P3)
  - netCDF3 static files with land-masked `geolon`/`geolat` (P4)
  - NWA monthly regrid on two `lon` grids (P5)
  - decadal `lead` as dates (P7)
  - seasonal forecast/reforecast member, fill value and layout problems (P8)
- **Kerchunk JSON contents are right where they exist**; all three JSONs that disagree
  with their NetCDF are PCI. The failures are around them: empty, misnamed, and 22 static
  JSONs pointing at *another region's* static file (P9).

## Chunking and the rebuild

- The user intends to argue that CEFI rebuild every NetCDF to one standard.
  `audit/rebuild.md` has a draft standard (v0, open questions listed) and the effort:
  about 250–1,000 core-hours and half a day on ~25 VMs for the newest releases, and
  about 3–4 weeks of engineering once the standard is agreed. A few problems need CEFI
  to regenerate from model output (PCI empty files, missing member 6, `T_adx` SSP585
  2045, NWA 0.0801° regrid).
- Rebuild pipelines must copy whole files locally before rechunking: reading through
  1 MB source chunks over the network ran at 8 MB/s, against about 250 MB/s for local
  decompression.

## The Source Coop daily stores are misplaced (internal; not in the report)

The user's Source Coop store `eeholmes/cefi/nepacific-icechunk`, built by this repo's
daily notebooks and `build_nep_icechunk_daily.py` from r20250912, appended the per-year
files with `append_dim="time"`. **All variables in `daily/raw/main` (14) and
`daily/regrid/main` (12) are misplaced.**
- Each year lands at chunk slot `floor(days so far / chunk)`: 1994 starts at index 300
  (labelled 1993-10-28).
- `chlos` and `phycos` have chunk 37, so 1994 starts at index 333.
- The `daily/*/aux` groups and all monthly groups spot-checked correct.

Earthmover's Arraylake store `NOAA-PMEL/cefi-nep-hindcast-daily` simply omits the
per-year variables and is correct where checked.

The user asked that the report not mention Source Coop: Earthmover is the (eventual)
production version, and its dropping those variables is the point to make. The report's
repro `02b_append_misplaces_data.py` demonstrates the append bug in a throwaway
in-memory store using r20260701. Fixing or flagging the Source Coop store is the user's
call and hasn't been done.

## Things that look wrong but aren't, or that are easy to get wrong

- **Chunk shapes that differ between variables are not a merge blocker**; each Zarr
  array has its own chunks. The blockers are a different time *axis*, and irregular
  chunks when *concatenating* one variable's files.
- **If a build ever uses NEP r20250912:** `so` for 1999 and 2001 has about 29 days a
  year of zeroed data, not just bad stamps, and the old template-time workaround hides
  it. It's fixed in r20260701.
- **Most "missing" Kerchunk JSONs are misnamed** (first character dropped, e.g.
  `hlos...json` for `chlos...nc`). Match JSONs to NetCDFs by the URL inside the JSON,
  never by filename.

## Running the audit on this hub

- Hub memory is capped at 3.9 GB and shared. More than about 6 worker processes hit the
  OOM killer, and a killed `multiprocessing.Pool` worker hangs the pool forever (its task
  is lost). If a scan stalls with idle workers, check `oom_kill` in
  `/sys/fs/cgroup/memory.events`.
- **Never use h5py `visititems` on these files.** `H5Ovisit` walks every chunk index; on
  the 43 GB PCI files that took 300 s per file instead of 1.6 s. `scan_headers.py`
  walks groups by hand.
- Don't `pkill -f`/`pgrep -f` a pattern that also appears in the Bash command itself:
  it kills the shell running it. Kill by PID.
- S3 reads from this bucket occasionally stall for many minutes. The scanners set
  `read_timeout`/`connect_timeout` and retries, and are resumable.
- VirtualiZarr needs 4–8 minutes per PCI 4-D raw file (1 MB chunks, about 80k per file).
