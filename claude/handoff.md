# Handoff — cefi-icechunks

Orientation for a new session. Not a task list.

## Repo state

- Builds **virtual** Icechunk stores (metadata + byte-range references) from CEFI
  regional MOM6 NetCDF files in `s3://noaa-oar-cefi-regional-mom6-pds` (us-east-1,
  anonymous read). Stores are written to Source Coop
  (`s3://us-west-2.opendata.source.coop/eeholmes/cefi/...`). Earthmover also builds
  stores on Arraylake (for example `NOAA-PMEL/cefi-nep-hindcast-daily`); the user treats
  those as the eventual production version.
- Existing build work covers only the **Northeast Pacific hindcast** (daily + monthly,
  raw + regrid): `build_nep_icechunk_{daily,monthly}.py`, `cefi_nep_*.ipynb`, and the
  `*_groups.json` files. These use the **old release r20250912**; the newest NEP release
  is r20260701.
- `audit/` holds the source-file audit (issue #5, merged in PR #7): scanners, `checks.py`,
  `repro/01–09`, `report.md` (full), `report-cefi.md` (the user's trimmed CEFI-facing
  version), and `rebuild.md` (draft standard and effort estimate). See
  `notes/source-file-problems.md`.
- `source-cefi-creds.json` holds temporary Source Coop write credentials. It is
  gitignored (`*-creds.json`) — never commit it.
- `LICENSE` is Apache-2.0 and the README has a `## Reuse and citation` section (PR #6).
- `cefi_nep_daily-raw.ipynb` has had a one-line uncommitted change for a while that
  Claude didn't make. Leave it unless the user says otherwise.

## Working principles

- Build from the NetCDFs with VirtualiZarr; CEFI's Kerchunk JSONs are an older workflow.
- Reports for CEFI cover only the newest release of each product, keep the Pacific
  Islands drafts separate or out, and cite Earthmover rather than the Source Coop
  stores. The user relays findings to CEFI; Claude doesn't file upstream.
- Hub memory is small (~3.9 GB). Scan metadata, not whole data variables; watch for
  OOM kills when running worker pools.

## Open threads

- **Issue #8:** the Source Coop `daily/raw/main` and `daily/regrid/main` groups hold
  misplaced data. They were built by appending per-year files with
  `append_dim="time"`, where the 100-day source chunk doesn't divide 365. The issue asks
  for a README warning and a decision on the groups; not started.
- **Next task (in `~/agent-skills`, not here):** record the append pitfall in the
  `virtual-icechunk` skill so new stores don't repeat it. The user isn't sure whether the
  answer is concat (which refuses these files) or something else. The evidence is
  `audit/report.md` P2, `audit/repro/02a` and `02b`, and
  `notes/source-file-problems.md`.
- Issue #5 is still open; PR #7 deliberately didn't close it.
