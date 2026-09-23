# CEFI source-file problems (audit, issue #5)

The full catalogue is `audit/report.md`. Every finding is in `audit/out/findings.csv`,
and each problem has a standalone script in `audit/repro/`. This note records what a
later session needs and could not easily reconstruct.

## Headline

- **Build from the newest release, not r20250912.** In every newest hindcast release
  except PCI monthly raw, all variables share one time axis. The 390/396 split
  (duplicated Jan–Jun 2025 tail), the daily series ending in different months, and the
  zeroed salinity belong to NEP r20250912 and its copy r20251001. The existing
  `build_nep_icechunk_*.py` scripts and the README still point at r20250912.
- **What still blocks one group per series** in the newest releases:
  - per-year daily files: the 100-step time chunk doesn't divide 365, and VirtualiZarr
    refuses to concatenate them (P1)
  - bundled `volcello` copies inside raw files (P6)
  - netCDF3 static files with land-masked `geolon`/`geolat` (P8)
  - NWA monthly regrid on three `lon` grids (P9)
  - broken PCI monthly raw files (P10)
  - forecast lead/member inconsistencies (P12, P13)
- **Kerchunk JSON contents are right where they exist** (byte ranges match VirtualiZarr).
  The failures are around them: empty, misnamed, pointing into other directories, and
  25 static JSONs pointing at *another region's* static file.

## Things that look wrong but aren't, or that are easy to get wrong

- **Chunk shapes that differ between variables are not a merge blocker**; each Zarr
  array has its own chunks. The blockers are a different time *axis*, and irregular
  chunks when *concatenating* one variable's files.
- **Salinity `so` 1999/2001 in r20250912 is zeroed data, not just bad stamps.** The
  earlier workaround (assigning a template time axis) hid about 29 days a year of
  salinity = 0. It's fixed in r20260701.
- **Most "missing" Kerchunk JSONs are misnamed** (first character dropped, e.g.
  `hlos...json` for `chlos...nc`). Match JSONs to NetCDFs by the URL inside the JSON,
  never by filename.
- **Seasonal reforecast init months differ by release** (Feb/Jun/Sep/Dec vs
  Jan/Apr/Jul/Oct). That's a schedule change, not missing inits.

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
