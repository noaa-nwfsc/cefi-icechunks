# Source bucket inventory (surveyed 2026-09-23)

`s3://noaa-oar-cefi-regional-mom6-pds`, anonymous read.

- 13,307 `.nc` files, 13,399 `.json` (Kerchunk references CEFI publishes beside the
  NetCDFs), ~37 TB total.
- Path pattern: `<region>/full_domain/<experiment>/<frequency>/<raw|regrid>/<release>/`.
  Each release directory is one "group" to audit — 46 of them.
- Regions: `northeast_pacific` (nep), `northwest_atlantic` (nwa), `pacific_islands` (pci).
- Experiments: `hindcast` (all three regions), and for NWA only `decadal_forecast`,
  `seasonal_forecast`, `seasonal_reforecast`, `multi_decadal_outlook`.
- Filename pattern (hindcast):
  `<var>.<region>.full.hcast.<freq>.<grid>.<release>.<YYYYMM>-<YYYYMM>.nc`.
  Some variables are one file for the full period; some daily variables are one file
  per year.
- Filename pattern (forecasts): `<var>.nwa.full.<dc_fcast|ss_refcast|...>.<freq>.<grid>.<release>.enss.i<YYYYMM>.nc`
  — one file per initialization, ensemble dimension inside.
- Oddities already seen in listings: `ocean_static.nc`, and stray `all.json`,
  `ocean_stati.json` in `northwest_atlantic/.../seasonal_reforecast/monthly/raw/r20250413`.
- Old releases sit beside new ones and have far fewer files (e.g. nep daily raw
  r20241015: 22 files vs r20260701: 414).

## Problems already confirmed (earthmover-support/cefi issues)

- #1: some `.nc` files have no Kerchunk `.json` (e.g. `co3os`, `no3` in nep monthly raw
  r20250912), so JSON-driven builders silently drop them.
- #3: per-year daily files use 100-day time chunks, which don't tile a 365/366-day
  year, so concatenation across years fails without variable-length chunking. 2025
  files end in different months for different variables. Salinity has bad time
  stamps in two years.
- #4: the 2-D ocean-monthly stream in nep monthly raw has 396 time steps with the last
  six months (Jan–Jun 2025) duplicated and a non-monotonic break. `volcello` is also
  bundled as a cell-measure variable in many files, so a naive merge pulls in a
  duplicate, corrupt copy.
