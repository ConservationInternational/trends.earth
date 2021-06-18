import datetime as dt
import tempfile
from pathlib import Path

from osgeo import gdal

from .. import (
    calculate_soc,
    log,
    utils,
    worker,
)
from ..areaofinterest import AOI
from ..jobs import models


def compute_soil_organic_carbon(
        soc_job: models.Job, area_of_interest: AOI) -> models.Job:
    # Select the initial and final bands from initial and final datasets
    # (in case there is more than one lc band per dataset)
    lc_initial_vrt = utils.save_vrt(
        soc_job.params.params["lc_initial_path"],
        soc_job.params.params["lc_initial_band_index"]
    )
    lc_final_vrt = utils.save_vrt(
        soc_job.params.params["lc_final_path"],
        soc_job.params.params["lc_final_band_index"]
    )
    lc_files = [lc_initial_vrt, lc_final_vrt]
    lc_vrts = []
    for index, path in enumerate(lc_files):
        vrt_path = tempfile.NamedTemporaryFile(suffix='.vrt').name
        # Add once since band numbers don't start at zero
        gdal.BuildVRT(
            vrt_path,
            lc_files[index],
            bandList=[index + 1],
            outputBounds=area_of_interest.get_aligned_output_bounds_deprecated(lc_initial_vrt),
            resolution='highest',
            resampleAlg=gdal.GRA_NearestNeighbour,
            separate=True
        )
        lc_vrts.append(vrt_path)
    custom_soc_vrt = utils.save_vrt(
        soc_job.params.params["custom_soc_path"],
        soc_job.params.params["custom_soc_band_index"]
    )
    climate_zones_path = Path(__file__).parents[1] / "data" / "IPCC_Climate_Zones.tif"
    in_files = [
        custom_soc_vrt,
        str(climate_zones_path),
    ] + lc_vrts

    in_vrt_path = tempfile.NamedTemporaryFile(suffix='.vrt').name
    log(u'Saving SOC input files to {}'.format(in_vrt_path))
    gdal.BuildVRT(
        in_vrt_path,
        in_files,
        resolution='highest',
        resampleAlg=gdal.GRA_NearestNeighbour,
        outputBounds=area_of_interest.get_aligned_output_bounds_deprecated(
            lc_initial_vrt),
        separate=True
    )
    job_output_path, dataset_output_path = utils.get_local_job_output_paths(soc_job)
    log(f'Saving soil organic carbon to {dataset_output_path!r}')
    # Lc bands start on band 3 as band 1 is initial soc, and band 2 is
    # climate zones
    lc_band_nums = list(range(3, len(lc_files) + 3))
    log(f'lc_band_nums: {lc_band_nums}')
    soc_worker = worker.StartWorker(
        calculate_soc.SOCWorker,
        'calculating change in soil organic carbon',
        in_vrt_path,
        str(dataset_output_path),
        lc_band_nums,
        soc_job.params.params["lc_years"],
        soc_job.params.params["fl"],
    )
    if soc_worker.success:
        soc_job.end_date = dt.datetime.now(dt.timezone.utc)
        soc_job.progress = 100
        bands = [
            models.JobBand(
                name="Soil organic carbon (degradation)",
                metadata={
                    "year_start": soc_job.params.params["lc_years"][0],
                    "year_end": soc_job.params.params["lc_years"][-1],
                }
            )
        ]
        for year in soc_job.params.params["lc_years"]:
            soc_band = models.JobBand(
                name="Soil organic carbon",
                metadata={
                    "year": year
                }
            )
            bands.append(soc_band)
        for year in soc_job.params.params["lc_years"]:
            lc_band = models.JobBand(
                name="Land cover (7 class)",
                metadata={
                    "year": year
                }
            )
            bands.append(lc_band)
        soc_job.results.bands = bands
        soc_job.results.local_paths = [dataset_output_path]
    else:
        raise RuntimeError("Error calculating soil organic carbon")
    return soc_job