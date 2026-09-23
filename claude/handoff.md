# Handoff — cefi-icechunks

Orientation for a new session. Not a task list.

## Repo state

- Builds **virtual** Icechunk stores (metadata + byte-range references) from CEFI
  regional MOM6 NetCDF files in `s3://noaa-oar-cefi-regional-mom6-pds` (us-east-1,
  anonymous read). Stores are written to Source Coop
  (`s3://us-west-2.opendata.source.coop/eeholmes/cefi/...`).
- Existing work covers only the **Northeast Pacific hindcast** (daily + monthly, raw +
  regrid): `build_nep_icechunk_{daily,monthly}.py`, `cefi_nep_*.ipynb`, and the
  `*_groups.json` files that record which variables went into which Icechunk group.
- `draft/` holds early exploratory notebooks; `Untitled*.ipynb` is gitignored scratch.
- `source-cefi-creds.json` holds temporary Source Coop write credentials. It is
  gitignored (`*-creds.json`) — never commit it.
- Two license files (`LICENSE_Apache_2.0`, `LICENSE_CC0`), no plain `LICENSE`, and no
  `## Reuse and citation` section in the README yet.

## Working principles

- The source files have defects (chunking mismatches across years, duplicated time
  steps, missing Kerchunk JSONs, bundled cell-measure variables, codec differences).
  Earthmover tracks what they found at https://github.com/earthmover-support/cefi/issues.
- Hub memory is small (~3.9 GB on this one). Scan headers/metadata and coordinate
  variables only; never pull full data variables over 13k files.

## Recent / open threads

- **Source-file audit done (issue #5, branch `audit-source-files-5`).** It covers all 46
  release directories. `audit/report.md` has the problem catalogue, `audit/repro/` has
  one script per problem, and the summary is in `notes/source-file-problems.md`. The
  audit only diagnoses; fixing and rebuilding are separate tasks. @eeholmes reports the
  findings to CEFI; Claude doesn't file upstream.
- Main takeaway: the newest releases (NEP r20260701, NWA r20250715, PCI r20260427)
  have one time axis per hindcast group. The current build scripts still use NEP
  r20250912, where most of the known problems live.
- Build from the NetCDFs with VirtualiZarr. CEFI's Kerchunk JSONs are an older workflow;
  they're audited, not relied on.
