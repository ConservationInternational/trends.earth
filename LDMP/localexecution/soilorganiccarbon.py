import os
import datetime as dt
import tempfile
from pathlib import Path

import numpy as np
from osgeo import (
    gdal,
    osr,
)

import LDMP.logger
from .. import (
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
    LDMP.logger.log(u'Saving SOC input files to {}'.format(in_vrt_path))
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
    LDMP.logger.log(f'Saving soil organic carbon to {dataset_output_path!r}')
    # Lc bands start on band 3 as band 1 is initial soc, and band 2 is
    # climate zones
    lc_band_nums = list(range(3, len(lc_files) + 3))
    LDMP.logger.log(f'lc_band_nums: {lc_band_nums}')
    soc_worker = worker.StartWorker(
        SOCWorker,
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


class SOCWorker(worker.AbstractWorker):
    def __init__(self, in_vrt, out_f, lc_band_nums, lc_years, fl):
        worker.AbstractWorker.__init__(self)
        self.in_vrt = in_vrt
        self.out_f = out_f
        self.lc_years = lc_years
        self.lc_band_nums = lc_band_nums
        self.fl = fl

    def work(self):
        ds_in = gdal.Open(self.in_vrt)

        soc_band = ds_in.GetRasterBand(1)
        clim_band = ds_in.GetRasterBand(2)

        block_sizes = soc_band.GetBlockSize()
        x_block_size = block_sizes[0]
        y_block_size = block_sizes[1]
        xsize = soc_band.XSize
        ysize = soc_band.YSize

        driver = gdal.GetDriverByName("GTiff")
        # Need a band for SOC degradation, plus bands for annual SOC, and for
        # annual LC
        ds_out = driver.Create(self.out_f, xsize, ysize, 1 + len(self.lc_years) * 2, gdal.GDT_Int16,
                               ['COMPRESS=LZW'])
        src_gt = ds_in.GetGeoTransform()
        ds_out.SetGeoTransform(src_gt)
        out_srs = osr.SpatialReference()
        out_srs.ImportFromWkt(ds_in.GetProjectionRef())
        ds_out.SetProjection(out_srs.ExportToWkt())

        # Setup a raster of climate regimes to use for coding Fl automatically
        clim_fl_map = np.array([[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
                                [0, .69, .8, .69, .8, .69, .8, .69, .8, .64, .48, .48, .58]])

        # stock change factor for land use - note the 99 and -99 will be
        # recoded using the chosen Fl option
        lc_tr_fl_0_map = np.array([[11, 12, 13, 14, 15, 16, 17,
                                    21, 22, 23, 24, 25, 26, 27,
                                    31, 32, 33, 34, 35, 36, 37,
                                    41, 42, 43, 44, 45, 46, 47,
                                    51, 52, 53, 54, 55, 56, 57,
                                    61, 62, 63, 64, 65, 66, 67,
                                    71, 72, 73, 74, 75, 76, 77],
                                   [1, 1, 99, 1, 0.1, 0.1, 1,
                                    1, 1, 99, 1, 0.1, 0.1, 1,
                                    -99, -99, 1, 1 / 0.71, 0.1, 0.1, 1,
                                    1, 1, 0.71, 1, 0.1, 0.1, 1,
                                    2, 2, 2, 2, 1, 1, 1,
                                    2, 2, 2, 2, 1, 1, 1,
                                    1, 1, 1, 1, 1, 1, 1]])

        # stock change factor for management regime
        lc_tr_fm_map = [[11, 12, 13, 14, 15, 16, 17,
                         21, 22, 23, 24, 25, 26, 27,
                         31, 32, 33, 34, 35, 36, 37,
                         41, 42, 43, 44, 45, 46, 47,
                         51, 52, 53, 54, 55, 56, 57,
                         61, 62, 63, 64, 65, 66, 67,
                         71, 72, 73, 74, 75, 76, 77],
                        [1, 1, 1, 1, 1, 1, 1,
                         1, 1, 1, 1, 1, 1, 1,
                         1, 1, 1, 1, 1, 1, 1,
                         1, 1, 1, 1, 1, 1, 1,
                         1, 1, 1, 1, 1, 1, 1,
                         1, 1, 1, 1, 1, 1, 1,
                         1, 1, 1, 1, 1, 1, 1]]

        # stock change factor for input of organic matter
        lc_tr_fo_map = [[11, 12, 13, 14, 15, 16, 17,
                         21, 22, 23, 24, 25, 26, 27,
                         31, 32, 33, 34, 35, 36, 37,
                         41, 42, 43, 44, 45, 46, 47,
                         51, 52, 53, 54, 55, 56, 57,
                         61, 62, 63, 64, 65, 66, 67,
                         71, 72, 73, 74, 75, 76, 77],
                        [1, 1, 1, 1, 1, 1, 1,
                         1, 1, 1, 1, 1, 1, 1,
                         1, 1, 1, 1, 1, 1, 1,
                         1, 1, 1, 1, 1, 1, 1,
                         1, 1, 1, 1, 1, 1, 1,
                         1, 1, 1, 1, 1, 1, 1,
                         1, 1, 1, 1, 1, 1, 1]]

        blocks = 0
        for y in range(0, ysize, y_block_size):
            if self.killed:
                LDMP.logger.log("Processing killed by user after processing {} out of {} blocks.".format(y, ysize))
                break
            self.progress.emit(100 * float(y) / ysize)
            if y + y_block_size < ysize:
                rows = y_block_size
            else:
                rows = ysize - y
            for x in range(0, xsize, x_block_size):
                if x + x_block_size < xsize:
                    cols = x_block_size
                else:
                    cols = xsize - x

                # Write initial soc to band 2 of the output file. Read SOC in
                # as float so the soc change calculations won't accumulate
                # error due to repeated truncation of ints
                soc = np.array(soc_band.ReadAsArray(x, y, cols, rows)).astype(np.float32)
                ds_out.GetRasterBand(2).WriteArray(soc, x, y)

                if self.fl == 'per pixel':
                    clim = np.array(clim_band.ReadAsArray(x, y, cols, rows)).astype(np.float32)
                    # Setup a raster of climate regimes to use for coding Fl
                    # automatically
                    clim_fl = remap(clim, clim_fl_map)

                tr_year = np.zeros(np.shape(soc))
                soc_chg = np.zeros(np.shape(soc))
                for n in range(len(self.lc_years) - 1):
                    t0 = float(self.lc_years[n])
                    t1 = float(self.lc_years[n + 1])

                    LDMP.logger.log(u'self.lc_band_nums: {}'.format(self.lc_band_nums))
                    lc_t0 = ds_in.GetRasterBand(self.lc_band_nums[n]).ReadAsArray(x, y, cols, rows)
                    lc_t1 = ds_in.GetRasterBand(self.lc_band_nums[n + 1]).ReadAsArray(x, y, cols, rows)

                    nodata = (lc_t0 == -32768) | (lc_t1 == -32768) | (soc == - 32768)
                    if self.fl == 'per pixel':
                        nodata[clim == -128] = True

                    # compute transition map (first digit for baseline land
                    # cover, and second digit for target year land cover), but
                    # only update where changes actually ocurred.
                    lc_tr = lc_t0 * 10 + lc_t1
                    lc_tr[(lc_t0 < 1) | (lc_t1 < 1)] < - -32768

                    ######################################################
                    # If more than one year has elapsed, need to split the
                    # period into two parts, and account for any requried
                    # changes in soc due to past lc transitions over the
                    # first part of the period, and soc changes due to lc
                    # changes that occurred during the period over the

                    # Calculate middle of period. Take the floor so that a
                    # transition that occurs when two lc layers are one
                    # year apart gets the full new soc_chg factor applied
                    # (rather than half), and none of the old soc_chg factor.
                    t_mid = t0 + np.floor((t1 - t0) / 2)

                    # Assume any lc transitions occurred in the middle of the
                    # period since we don't know the actual year of transition.
                    # Apply old soc change for appropriate number of years for
                    # pixels that had a transition > tr_year ago but less than
                    # 20 years prior to the middle of this period. Changes
                    # occur over a twenty year period, and then change stops.
                    if n > 0:
                        # Don't consider transition in lc at beginning of the
                        # period for the first period (as there is no data on
                        # what lc was prior to the first period, so soc_chg is
                        # undefined)
                        yrs_lc_0 = t_mid - tr_year
                        yrs_lc_0[yrs_lc_0 > 20] = 20
                        soc = soc - soc_chg * yrs_lc_0
                        soc_chg[yrs_lc_0 == 20] = 0

                    ######################################################
                    # Calculate new soc_chg and apply it over the second
                    # half of the period

                    # stock change factor for land use
                    lc_tr_fl = remap(np.array(lc_tr).astype(np.float32), lc_tr_fl_0_map)
                    if self.fl == 'per pixel':
                        lc_tr_fl[lc_tr_fl == 99] = clim_fl[lc_tr_fl == 99]
                        lc_tr_fl[lc_tr_fl == -99] = 1. / clim_fl[lc_tr_fl == -99]
                    else:
                        lc_tr_fl[lc_tr_fl == 99] = self.fl
                        lc_tr_fl[lc_tr_fl == -99] = 1. / self.fl

                    # stock change factor for management regime
                    lc_tr_fm = remap(lc_tr, lc_tr_fm_map)

                    # stock change factor for input of organic matter
                    lc_tr_fo = remap(lc_tr, lc_tr_fo_map)

                    # Set the transition year to the middle of the period for
                    # pixels that had a change in cover
                    tr_year[lc_t0 != lc_t1] = t_mid

                    # Calculate a new soc change for pixels that changed
                    soc_chg[lc_t0 != lc_t1] = (soc[lc_t0 != lc_t1] - \
                                               soc[lc_t0 != lc_t1] * \
                                               lc_tr_fl[lc_t0 != lc_t1] * \
                                               lc_tr_fm[lc_t0 != lc_t1] * \
                                               lc_tr_fo[lc_t0 != lc_t1]) / 20

                    yrs_lc_1 = t1 - tr_year
                    # Subtract the length of the first half of the period from
                    # yrs_lc_1 for pixels that weren't changed - these pixels
                    # have already had soc_chg applied for the first portion of
                    # the period
                    yrs_lc_1[lc_t0 == lc_t1] = yrs_lc_1[lc_t0 == lc_t1] - (t_mid - t0)
                    yrs_lc_1[yrs_lc_1 > 20] = 20
                    soc = soc - soc_chg * yrs_lc_1
                    soc_chg[yrs_lc_1 == 20] = 0

                    # Write out this SOC layer. Note the first band of ds_out
                    # is soc degradation, and the second band is the initial
                    # soc. As n starts at 0, need to add 3 so that the first
                    # soc band derived from LC change soc band is written to
                    # band 3 of the output file
                    soc[nodata] = -32768
                    ds_out.GetRasterBand(n + 3).WriteArray(soc, x, y)

                # Write out the percent change in SOC layer
                soc_initial = ds_out.GetRasterBand(2).ReadAsArray(x, y, cols, rows)
                soc_final = ds_out.GetRasterBand(2 + len(self.lc_band_nums) - 1).ReadAsArray(x, y, cols, rows)
                soc_initial = np.array(soc_initial).astype(np.float32)
                soc_final = np.array(soc_final).astype(np.float32)
                soc_pch = ((soc_final - soc_initial) / soc_initial) * 100
                soc_pch[nodata] = -32768
                ds_out.GetRasterBand(1).WriteArray(soc_pch, x, y)

                # Write out the initial and final lc layers
                lc_bl = ds_in.GetRasterBand(self.lc_band_nums[0]).ReadAsArray(x, y, cols, rows)
                ds_out.GetRasterBand(1 + len(self.lc_band_nums) + 1).WriteArray(lc_bl, x, y)
                lc_tg = ds_in.GetRasterBand(self.lc_band_nums[-1]).ReadAsArray(x, y, cols, rows)
                ds_out.GetRasterBand(1 + len(self.lc_band_nums) + 2).WriteArray(lc_tg, x, y)

                blocks += 1

        if self.killed:
            del ds_in
            del ds_out
            os.remove(self.out_f)
            return None
        else:
            return True


def remap(a, remap_list):
    for value, replacement in zip(remap_list[0], remap_list[1]):
        a[a == value] = replacement
    return a
