import datetime as dt
import json
import tempfile
from pathlib import Path

from osgeo import gdal
from te_algorithms.gdal.util import combine_all_bands_into_vrt
from te_schemas.results import URI, DataType, Raster, RasterFileType, RasterResults
from te_schemas.results import Band as JobBand

from ..areaofinterest import AOI
from ..jobs.models import Job
from ..logger import log

NODATA_VALUE = -32768
UNSIGNED_DATATYPES = (DataType.BYTE, DataType.UINT16, DataType.UINT32)

GDAL_CONFIG = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.tiff",
}


def _vsicurl(href):
    return f"/vsicurl/{href}"


def _union_bounds(bounds):
    return [
        min(b[0] for b in bounds),
        min(b[1] for b in bounds),
        max(b[2] for b in bounds),
        max(b[3] for b in bounds),
    ]


def _group_assets_by_datatype(assets):
    groups = {}
    for asset in assets:
        ds = gdal.Open(_vsicurl(asset["href"]))
        datatype = DataType(gdal.GetDataTypeName(ds.GetRasterBand(1).DataType))
        groups.setdefault(datatype, []).append(asset)
        ds = None
    return groups


def download_stac(
    job: Job,
    area_of_interest: AOI,
    job_output_path: Path,
    dataset_output_path: Path,
    progress_callback,
    killed_callback,
):
    return _stac_to_raster(
        job,
        area_of_interest,
        dataset_output_path,
        progress_callback,
        killed_callback,
        online=False,
    )


def view_stac(
    job: Job,
    area_of_interest: AOI,
    job_output_path: Path,
    dataset_output_path: Path,
    progress_callback,
    killed_callback,
):
    return _stac_to_raster(
        job,
        area_of_interest,
        dataset_output_path.with_suffix(".vrt"),
        progress_callback,
        killed_callback,
        online=True,
    )


def _stac_to_raster(
    job: Job,
    area_of_interest: AOI,
    dataset_output_path: Path,
    progress_callback,
    killed_callback,
    online: bool,
):
    assets = job.params["assets"]

    with gdal.config_options(GDAL_CONFIG):
        groups = _group_assets_by_datatype(assets)

        first_layer_link = _vsicurl(assets[0]["href"])
        output_bounds = _union_bounds(
            area_of_interest.get_aligned_output_bounds(first_layer_link)
        )
        gt = gdal.Open(first_layer_link).GetGeoTransform()

        cutline_file = tempfile.NamedTemporaryFile(suffix=".geojson", delete=False)
        cutline_file.write(json.dumps(area_of_interest.get_geojson()).encode())
        cutline_file.close()

        rasters = {}
        for n, (datatype, group_assets) in enumerate(groups.items()):
            if len(groups) > 1:
                out_file = dataset_output_path.with_name(
                    f"{dataset_output_path.stem}_{datatype.value}"
                    f"{dataset_output_path.suffix}"
                )
            else:
                out_file = dataset_output_path

            if online:
                # The online VRT keeps reading from this source VRT
                in_vrt = str(out_file.with_name(f"{out_file.stem}_source.vrt"))
            else:
                in_vrt = tempfile.NamedTemporaryFile(suffix=".vrt").name
            ds_vrt = gdal.BuildVRT(
                in_vrt,
                [_vsicurl(group["href"]) for group in group_assets],
                separate=True,
            )
            if ds_vrt is None:
                raise RuntimeError(f"Failed to create VRT for {datatype.value} assets")
            ds_vrt.FlushCache()
            ds_vrt = None

            no_data_value = NODATA_VALUE
            if datatype in UNSIGNED_DATATYPES:
                ds = gdal.Open(_vsicurl(group_assets[0]["href"]))
                no_data_value = ds.GetRasterBand(1).GetNoDataValue()
                ds = None
                if no_data_value is None:
                    raise RuntimeError(
                        f"{datatype.value} asset {group_assets[0]['key']} has no nodata value"
                    )
                no_data_value = int(no_data_value)

            def _progress(fraction, message, data, n=n):
                progress_callback(100 * (n + fraction) / len(groups))
                return 0 if killed_callback() else 1

            if online:
                log(
                    f"Creating online VRT of {len(group_assets)} asset(s) at {out_file}"
                )
                output_format = {"format": "VRT"}
            else:
                log(f"Downloading {len(group_assets)} STAC asset(s) to {out_file}")
                output_format = {
                    "format": "GTiff",
                    "creationOptions": ["COMPRESS=LZW", "TILED=YES"],
                }
            res = gdal.Warp(
                str(out_file),
                in_vrt,
                **output_format,
                cutlineDSName=cutline_file.name,
                outputBounds=output_bounds,
                xRes=gt[1],
                yRes=abs(gt[5]),
                dstNodata=no_data_value,
                outputType=gdal.GetDataTypeByName(datatype.value),
                resampleAlg=gdal.GRA_NearestNeighbour,
                callback=_progress,
            )
            if res is None:
                raise RuntimeError(f"Failed to download {datatype.value} assets")
            res = None

            rasters[datatype.value] = Raster(
                uri=URI(uri=out_file),
                bands=[
                    JobBand(
                        name=group["style"],
                        metadata={
                            "stac_collection": job.params["stac_collection"],
                            "asset": group["key"],
                            "asset_title": group["title"],
                        },
                        no_data_value=no_data_value,
                    )
                    for group in group_assets
                ],
                datatype=datatype,
                filetype=RasterFileType.GEOTIFF,
            )

        Path(cutline_file.name).unlink()

    if len(rasters) > 1:
        vrt_file = dataset_output_path.with_suffix(".vrt")
        combine_all_bands_into_vrt(
            [r.uri.uri for r in rasters.values()],
            vrt_file,
            band_names=[
                b.metadata["asset_title"] for r in rasters.values() for b in r.bands
            ],
        )
        uri = URI(uri=vrt_file)
    else:
        uri = [*rasters.values()][0].uri

    job.end_date = dt.datetime.now(dt.timezone.utc)
    job.progress = 100
    return RasterResults(name=job.params["stac_collection"], uri=uri, rasters=rasters)
