# CEFI Northeast Pacific MOM6 Icechunk Demo

This dataset is a demonstration Icechunk repository built from NOAA Changing Ecosystems and Fisheries Initiative (CEFI) regional MOM6 NetCDF files for the Northeast Pacific. The Icechunk repository stores metadata and virtual chunk references, while the original NetCDF data chunks remain in the public NOAA S3 bucket.

```python
import icechunk as ic
import xarray as xr
url = "https://data.source.coop/eeholmes/cefi/nepacific-icechunk"
storage = ic.http_storage(url)
containers = ic.Repository.open(storage).config.virtual_chunk_containers or []
store = ic.Repository.open(
    storage,
    authorize_virtual_chunk_access={prefix: None for prefix in containers},
).readonly_session("main").store

ds = xr.open_zarr(store, consolidated=False, group="monthly/raw/main")
ds
```

This used:

- [Icechunk](https://icechunk.io/)
- [VirtualiZarr](https://virtualizarr.readthedocs.io/)
- [Xarray](https://docs.xarray.dev/)
- [CEFI public object storage](https://noaa-oar-cefi-regional-mom6-pds.s3.amazonaws.com/index.html#northeast_pacific/full_domain/hindcast/)
- NOAA CEFI regional MOM6 output

GitHub repo (private): [https://github.com/noaa-nwfsc/cefi-icechunks](https://github.com/noaa-nwfsc/cefi-icechunks)<br>
Vizualization: [GridLook Viz](https://eeholmes.github.io/gridlook/#https://data.source.coop/eeholmes/cefi/nepacific-icechunk::catalog=static/catalog.json::projectionCenterLat=0::projectionCenterLon=0::varname=monthly/main/chlos::dimIndices_time=0::camerastate=JYw7EsIwDETv4tr2aCVZH67CpKCgSJPwCRXD3TFDt7O7773LbX-ux7pv5XRu2Ud4JiFcdCSjNunhSFYTGFEgrYI7x4yuHCEIWWq5vy7H9bH9PTR3xdRkwmASE2rUkXAWNZ86JRX9lYOHOKcZRwqzVuru4cPmJzDSfPl8AQ::invertcolormap=false::colormap=turbo)

The CEFI portal provides access to information about past and future conditions for U.S. coastal regions, including regional ocean model output intended for analysis, visualization, and management-relevant applications.

## Dataset summary

| Item | Description |
|---|---|
| Dataset | CEFI Northeast Pacific regional MOM6 hindcast demo |
| Source files | CEFI regional MOM6 NetCDF files |
| Source bucket | `s3://noaa-oar-cefi-regional-mom6-pds` |
| Source prefix | `northeast_pacific/full_domain/hindcast/<frequency>/regrid/r20250912` |
| Source region | `us-east-1` |
| Icechunk location | `s3://us-west-2.opendata.source.coop/eeholmes/cefi/nepacific-icechunk` |
| Icechunk region | `us-west-2` |
| Storage pattern | Virtual chunks pointing back to the original NOAA NetCDF files |
| Domain | Northeast Pacific |
| Frequency | daily/monthly |
| Grid | Regridded regular latitude/longitude |
| Access | Public / anonymous for reading |

## What is in the Icechunk store on Source Coop?

The Icechunk store does **not** copy the full model output out of the original NetCDF files. Instead, it stores virtual references that point back to byte ranges in the original public NOAA S3 files.

That means:

- The Icechunk repo is small relative to the source data.
- The original data remain in NOAA's public bucket.
- Users can open the dataset with Xarray as if it were a Zarr-like dataset.
- Reading actual data values will fetch the needed byte ranges from the original NetCDF files.

## Example source files:

```text
s3://noaa-oar-cefi-regional-mom6-pds/northeast_pacific/full_domain/hindcast/daily/regrid/r20250912/chlos.nep.full.hcast.daily.regrid.r20250912.199301-199312.nc
s3://noaa-oar-cefi-regional-mom6-pds/northeast_pacific/full_domain/hindcast/daily/regrid/r20250912/dissic.nep.full.hcast.daily.regrid.r20250912.199301-199312.nc
```

## Icechunk layout

The source archive contains variables with different file layouts. Some variables are stored as one file per year, while others are stored as one full-period file. Due to the differing time chunking, these files cannot be merged into one Icechunk store. Instead this Icechunk repository uses separate groups for those layouts.

Group names:

```text
daily
    daily/raw
        daily/raw/aux
        daily/raw/main
    daily/regrid
        daily/regrid/aux
        daily/regrid/main
monthly
    monthly/raw
        monthly/raw/aux1
        monthly/raw/main
        monthly/raw/ice_static
        monthly/raw/aux2
        monthly/raw/ocean_static
    monthly/regrid
        monthly/regrid/aux
        monthly/regrid/aux2
        monthly/regrid/main
```

## Open the dataset in Python

These Icechunks stores use references to public data in other cloud storage and we need to explicitly authorize access.

```python
import icechunk as ic
import xarray as xr

url = "https://data.source.coop/eeholmes/cefi/nepacific-icechunk"
group_name = "monthly/raw/main" # use "/" if no groups

storage = ic.http_storage(url)
containers = ic.Repository.open(storage).config.virtual_chunk_containers or []
store = ic.Repository.open(
    storage,
    authorize_virtual_chunk_access={prefix: None for prefix in containers},
).readonly_session("main").store

ds = xr.open_zarr(store, consolidated=False, group=group_name)
ds
```

## Plot a surface variable

Using `slice()` is a bit more memory safe for big data.

```python
import matplotlib.pyplot as plt

da = (
    ds["chl"]
    .isel(time=slice(0, 1), z_l=slice(0, 1))
    .squeeze(drop=True)
)

da.plot(
    x="lon",
    y="lat",
    figsize=(10, 5),
    cmap = "turbo_r"
)

plt.figure(figsize=(8, 5))
plt.show()
```

## Creating the Icechunk stores

See the example notebooks `cefi_nep_monthly.ipynb` and `cefi_nep_daily.ipynb` for the code that created the icechunk stores. 

## Reuse and citation

This work is released under the [Apache License 2.0](LICENSE). You are free to use,
copy, modify, and redistribute it, including commercially. If you use it in published
work, in a presentation, or in another repository, please give attribution:

> Holmes, E.E. (2026). *CEFI Icechunks*. noaa-nwfsc/cefi-icechunks.
> https://github.com/noaa-nwfsc/cefi-icechunks

BibTeX:

```bibtex
@software{holmes_cefi_icechunks_2026,
  author  = {Holmes, Eli E.},
  title   = {CEFI Icechunks},
  year    = {2026},
  url     = {https://github.com/noaa-nwfsc/cefi-icechunks}
}
```

### The CEFI data

The Apache license covers this repository's code and documentation, not the model
output. The Icechunk stores hold only virtual references to NOAA CEFI regional MOM6
NetCDF files, which stay unmodified in NOAA's public bucket; see the license and use
constraints of the original data. Please cite the original NOAA CEFI regional MOM6 data
product when using the data scientifically. The Icechunk stores are a derived access
layer for demonstration and teaching purposes.

Useful project links:

- NOAA CEFI portal: https://psl.noaa.gov/cefi_portal/
- CEFI data cookbook: https://noaa-cefi-portal.github.io/cefi-cookbook/
