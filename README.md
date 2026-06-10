# CEFI Northeast Pacific MOM6 Icechunk Demo

This dataset is a demonstration Icechunk repository built from NOAA Changing Ecosystems and Fisheries Initiative (CEFI) regional MOM6 NetCDF files for the Northeast Pacific. The Icechunk repository stores metadata and virtual chunk references, while the original NetCDF data chunks remain in the public NOAA S3 bucket.

This example is intended for teaching cloud-native access patterns for archival NetCDF data using:

- [Icechunk](https://icechunk.io/)
- [VirtualiZarr](https://virtualizarr.readthedocs.io/)
- [Xarray](https://docs.xarray.dev/)
- Public object storage
- NOAA CEFI regional MOM6 output

The CEFI portal provides access to information about past and future conditions for U.S. coastal regions, including regional ocean model output intended for analysis, visualization, and management-relevant applications.

## Dataset summary

| Item | Description |
|---|---|
| Dataset | CEFI Northeast Pacific regional MOM6 hindcast demo |
| Source files | CEFI regional MOM6 NetCDF files |
| Source bucket | `s3://noaa-oar-cefi-regional-mom6-pds` |
| Source prefix | `northeast_pacific/full_domain/hindcast/daily/regrid/r20250912` |
| Source region | `us-east-1` |
| Icechunk location | `s3://us-west-2.opendata.source.coop/eeholmes/cefi/nepacific-icechunk` |
| Icechunk region | `us-west-2` |
| Storage pattern | Virtual chunks pointing back to the original NOAA NetCDF files |
| Domain | Northeast Pacific |
| Frequency | Daily |
| Grid | Regridded regular latitude/longitude |
| Access | Public / anonymous for reading |

## What is in this repository?

This repository contains notebooks to create Icechunk stores. The Icechunk store does **not** copy the full model output out of the original NetCDF files. Instead, it stores virtual references that point back to byte ranges in the original public NOAA S3 files.

That means:

- The Icechunk repo is small relative to the source data.
- The original data remain in NOAA's public bucket.
- Users can open the dataset with Xarray as if it were a Zarr-like dataset.
- Reading actual data values will fetch the needed byte ranges from the original NetCDF files.

## Source data

The source NetCDF files are from the public NOAA CEFI regional MOM6 bucket:

```text
s3://noaa-oar-cefi-regional-mom6-pds/northeast_pacific/full_domain/hindcast/daily/regrid/r20250912
```

Example source files:

```text
s3://noaa-oar-cefi-regional-mom6-pds/northeast_pacific/full_domain/hindcast/daily/regrid/r20250912/chlos.nep.full.hcast.daily.regrid.r20250912.199301-199312.nc
s3://noaa-oar-cefi-regional-mom6-pds/northeast_pacific/full_domain/hindcast/daily/regrid/r20250912/dissic.nep.full.hcast.daily.regrid.r20250912.199301-199312.nc
```

The Icechunk repo contains virtual chunk references back to these source NetCDF files.

## Icechunk layout

The source archive contains variables with different file layouts. Some variables are stored as one file per year, while others are stored as one full-period file. Due to the differing time chunking, these files cannot be merged into one Icechunk store. Instead this Icechunk repository uses separate groups for those layouts.

Group names:

```text
/yearly
/full_period
```

The `yearly` group is for variables with one file per year, such as `chlos`, `dissic`, `no3`, `o2`, `phycos`, `po4`, `si`, `talk`, `thetao`, `volcello`, and `vollcello`.

The `full_period` group is for variables stored as one longer file, such as bottom or surface summary variables. These are kept separate because their source files use a different time layout and chunking pattern.

## Open the dataset in Python

```python
import icechunk
import xarray as xr

# -------------------------------------------------------------------
# 1. Source data: original NOAA CEFI NetCDF files
# -------------------------------------------------------------------
source_data_bucket = "s3://noaa-oar-cefi-regional-mom6-pds"
source_data_prefix = "northeast_pacific/full_domain/hindcast/daily/regrid/r20250912"
source_data_region = "us-east-1"

source_data_url_prefix = source_data_bucket.rstrip("/") + "/"

# -------------------------------------------------------------------
# 2. Icechunk repo: public Source Cooperative location
# -------------------------------------------------------------------
icechunk_bucket = "us-west-2.opendata.source.coop"
icechunk_prefix = "eeholmes/cefi/nepacific-icechunk"
icechunk_region = "us-west-2"

# -------------------------------------------------------------------
# 3. Authorize access to the original NOAA virtual chunks
# -------------------------------------------------------------------
# The Icechunk repo contains virtual references back to the public
# NOAA CEFI S3 bucket. Use anonymous access for these chunks.
credentials = icechunk.containers_credentials({
    source_data_url_prefix: icechunk.s3_credentials(anonymous=True)
})

# -------------------------------------------------------------------
# 4. Tell Icechunk which external virtual chunk locations are allowed
# -------------------------------------------------------------------
config = icechunk.RepositoryConfig.default()
config.set_virtual_chunk_container(
    icechunk.VirtualChunkContainer(
        url_prefix=source_data_url_prefix,
        store=icechunk.s3_store(
            region=source_data_region,
            anonymous=True,
        ),
    ),
)

# -------------------------------------------------------------------
# 5. Point to the public Icechunk repo on Source Cooperative
# -------------------------------------------------------------------
storage = icechunk.s3_storage(
    bucket=icechunk_bucket,
    prefix=icechunk_prefix,
    region=icechunk_region,
    anonymous=True,
)

# -------------------------------------------------------------------
# 6. Open the Icechunk repo
# -------------------------------------------------------------------
repo = icechunk.Repository.open(
    storage,
    config=config,
    authorize_virtual_chunk_access=credentials,
)

session = repo.readonly_session(branch="main")
```

## Open the yearly-file variables

```python
ds_yearly = xr.open_zarr(
    session.store,
    group="yearly",
    consolidated=False,
    chunks=None,
)

ds_yearly
```

## Open the full-period-file variables

```python
ds_full_period = xr.open_zarr(
    session.store,
    group="full_period",
    consolidated=False,
    chunks=None,
)

ds_full_period
```

If only one group has been created so far, open that group and skip the other one.

## Plot a surface variable

```python
import hvplot.xarray

ds_yearly["chlos"].isel(time=0).hvplot.quadmesh(
    rasterize=True,
    x="lon",
    y="lat",
    cmap="turbo_r",
    title="CEFI Northeast Pacific chlos",
    width=800,
    height=500,
)
```

## Plot a variable with depth

Some variables include a vertical dimension such as `z_l`.

```python
ds_yearly["thetao"].isel(time=0, z_l=0).hvplot.quadmesh(
    rasterize=True,
    x="lon",
    y="lat",
    cmap="turbo_r",
    title="CEFI Northeast Pacific thetao, surface layer",
    width=800,
    height=500,
)
```

## Creating or updating the Icechunk repo

Temporary Source Cooperative credentials are used only when creating or updating the Icechunk repository. They are not needed for public read access.

The credentials file used for writing is:

```text
source-cefi-creds.json
```

Example write setup:

```python
import json
import icechunk

icechunk_bucket = "us-west-2.opendata.source.coop"
icechunk_prefix = "eeholmes/cefi/nepacific-icechunk"
icechunk_region = "us-west-2"
icechunk_creds = "source-cefi-creds.json"

with open(icechunk_creds) as f:
    source_creds = json.load(f)

storage = icechunk.s3_storage(
    bucket=icechunk_bucket,
    prefix=icechunk_prefix,
    region=icechunk_region,
    access_key_id=source_creds["AccessKeyId"],
    secret_access_key=source_creds["SecretAccessKey"],
    session_token=source_creds["SessionToken"],
)
```

## Notes on source-file layout

The source files are organized by variable. Some variables have one file per year, while other variables have one file covering a longer time period.

For the yearly-file variables, the Icechunk creation workflow opens matching yearly files, merges variables for that year, and appends the merged virtual dataset along `time`.

For full-period variables, the source files use a different time layout and chunking pattern. These variables are best handled separately, for example in a separate Icechunk group.

## Data quality notes

This Icechunk repository is a virtual access layer over the original NetCDF files. It does not modify the original source data. Any source-file metadata issues should be documented in the notebook or workflow used to create the repository.

For example, during testing,  `so` source files for 1999 and 2001 had invalid time coordinate labels in the original NetCDF file. The time stamps were corrected but the `so` data for these may be invalid.

## Citation and attribution

Please cite the original NOAA CEFI regional MOM6 data product when using the data scientifically. This Icechunk repository is a derived access layer for demonstration and teaching purposes; the underlying data are from NOAA.

Useful project links:

- NOAA CEFI portal: https://psl.noaa.gov/cefi_portal/
- CEFI data cookbook: https://noaa-cefi-portal.github.io/cefi-cookbook/

## License

See the license and use constraints for the original NOAA CEFI regional MOM6 data. This repository provides virtual access to that public source data and does not modify the original NetCDF files.
