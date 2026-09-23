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

- Planning a systematic audit of every file group in the bucket for defects that
  block Icechunk builds. Diagnose and write repro code only; fixing is a later task.
  See `notes/bucket-inventory.md`.
