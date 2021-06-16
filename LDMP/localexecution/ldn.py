import dataclasses
import datetime as dt
import enum
import json
import tempfile
import typing
from pathlib import Path

import numpy as np
import openpyxl
from openpyxl.drawing.image import Image
from osgeo import gdal
import qgis.core

from .. import (
    areaofinterest,
    calculate,
    calculate_ldn,
    data_io,
    log,
    summary,
    utils,
    worker,
)
from ..jobs import (
    manager,
    models,
)


class LdnProductivityMode(enum.Enum):
    TRENDS_EARTH = "Trends.Earth productivity"
    JRC_LPD = "JRC LPD"


@dataclasses.dataclass()
class SummaryTable:
    soc_totals: np.ndarray
    lc_totals: np.ndarray
    trans_prod_xtab: np.ndarray
    sdg_tbl_overall: np.ndarray
    sdg_tbl_prod: np.ndarray
    sdg_tbl_soc: np.ndarray
    sdg_tbl_lc: np.ndarray


@dataclasses.dataclass()
class LdnInputInfo:
    path: Path
    main_band: models.JobBand
    main_band_index: int
    aux_band_indexes: typing.List[int]
    years: typing.List[int]


def _get_ldn_inputs(
        data_selection_widget: data_io.WidgetDataIOSelectTELayerExisting,
        aux_band_name: str,
        sort_property: str = "year"
) -> LdnInputInfo:
    usable_band_info = data_selection_widget.get_usable_band_info()
    log(f"usable_band_info: {usable_band_info}")
    log(f"usable_band_info.path: {usable_band_info.path}")
    main_band = usable_band_info.band_info
    main_band_index = usable_band_info.band_index
    aux_bands = []
    for band_index, job_band in enumerate(usable_band_info.job.results.bands):
        if job_band.name == aux_band_name:
            aux_bands.append((job_band, band_index+1))
    sorted_aux_bands = sorted(aux_bands, key=lambda i: i[0].metadata[sort_property])
    aux_band_indexes = [info[1] for info in sorted_aux_bands]
    years = [i[0].metadata[sort_property] for i in sorted_aux_bands]
    return LdnInputInfo(
        path=usable_band_info.path,
        main_band=main_band,
        main_band_index=main_band_index,
        aux_band_indexes=aux_band_indexes,
        years=years
    )


def get_main_sdg_15_3_1_job_params(
        task_name: str,
        aoi,
        prod_mode: str,
        combo_layer_lc: data_io.WidgetDataIOSelectTELayerExisting,
        combo_layer_soc: data_io.WidgetDataIOSelectTELayerExisting,
        combo_layer_traj: data_io.WidgetDataIOSelectTELayerExisting,
        combo_layer_perf: data_io.WidgetDataIOSelectTELayerExisting,
        combo_layer_state: data_io.WidgetDataIOSelectTELayerExisting,
        combo_layer_lpd: data_io.WidgetDataIOSelectTELayerImport,
        task_notes: typing.Optional[str] = "",
) -> typing.Dict:
    land_cover_input_paths = _get_ldn_inputs(
        combo_layer_lc, "Land cover (7 class)")
    soil_organic_carbon_input_paths = _get_ldn_inputs(
        combo_layer_soc, "Soil organic carbon")
    crosses_180th, geojsons = aoi.bounding_box_gee_geojson()

    traj_path = None
    traj_index = None
    perf_path = None
    perf_index = None
    state_path = None
    state_index = None
    lpd_path = None
    lpd_index = None
    if prod_mode == LdnProductivityMode.TRENDS_EARTH.value:
        traj_band_info = combo_layer_traj.get_usable_band_info()
        traj_path = str(traj_band_info.path)
        traj_index = traj_band_info.band_index
        perf_band_info = combo_layer_perf.get_usable_band_info()
        perf_path = str(perf_band_info.path)
        perf_index = perf_band_info.band_index
        state_band_info = combo_layer_state.get_usable_band_info()
        state_path = str(state_band_info.path)
        state_index = state_band_info.band_index
    elif prod_mode == LdnProductivityMode.JRC_LPD.value:
        lpd_band_info = combo_layer_lpd.get_usable_band_info()
        lpd_path = str(lpd_band_info.path)
        lpd_index = lpd_band_info.band_index

    return {
        "task_name": task_name,
        "task_notes": task_notes,
        "prod_mode": prod_mode,
        "layer_lc_path": str(land_cover_input_paths.path),
        "layer_lc_main_band_index": land_cover_input_paths.main_band_index,
        "layer_lc_aux_band_indexes": land_cover_input_paths.aux_band_indexes,
        "layer_lc_years": land_cover_input_paths.years,
        "layer_soc_path": str(soil_organic_carbon_input_paths.path),
        "layer_soc_main_band_index": soil_organic_carbon_input_paths.main_band_index,
        "layer_soc_aux_band_indexes": soil_organic_carbon_input_paths.aux_band_indexes,
        "layer_soc_years": soil_organic_carbon_input_paths.years,
        "layer_traj_path": traj_path,
        "layer_traj_band_index": traj_index,
        "layer_perf_path": perf_path,
        "layer_perf_band_index": perf_index,
        "layer_state_path": state_path,
        "layer_state_band_index": state_index,
        "layer_lpd_path": lpd_path,
        "layer_lpd_band_index": lpd_index,
        "crs": aoi.get_crs_dst_wkt(),
        "geojsons": json.dumps(geojsons),
        "crosses_180th": crosses_180th,
    }


def compute_ldn(
        ldn_job: models.Job, area_of_interest: areaofinterest.AOI) -> models.Job:
    """Calculate final SDG 15.3.1 indicator and save its outputs to disk too."""
    lc_files = _prepare_land_cover_file_paths(ldn_job)
    lc_band_nums = np.arange(len(lc_files)) + 1
    soc_files = _prepare_soil_organic_carbon_file_paths(ldn_job)
    soc_band_nums = np.arange(len(lc_files)) + 1 + lc_band_nums.max()

    # NOTE: temporarily setting the status as the final value in order to determine
    # the target filepath for the processing's outputs
    previous_status = ldn_job.status
    ldn_job.status = models.JobStatus.GENERATED_LOCALLY
    job_output_path = manager.job_manager.get_job_file_path(ldn_job)
    ldn_job.status = previous_status
    log(f"inside compute_ldn current job status: {ldn_job.status}")

    _, wkt_bounding_boxes = area_of_interest.meridian_split("layer", "wkt", warn=False)
    summary_table_stable_kwargs = {
        "wkt_bounding_boxes": wkt_bounding_boxes,
        "in_files": lc_files + soc_files,
        "lc_band_nums": lc_band_nums,
        "soc_band_nums": soc_band_nums,
        "output_job_path": job_output_path
    }
    prod_mode = ldn_job.params.params["prod_mode"]
    if prod_mode == LdnProductivityMode.TRENDS_EARTH.value:
        traj, perf, state = _prepare_trends_earth_mode_vrt_paths(ldn_job)
        summary_table, output_ldn_path = _compute_summary_table_from_te_productivity(
            traj_vrt=traj,
            perf_vrt=perf,
            state_vrt=state,
            **summary_table_stable_kwargs
        )
    elif prod_mode == LdnProductivityMode.JRC_LPD.value:
        lpd = _prepare_jrc_lpd_mode_vrt_path(ldn_job)
        summary_table, output_ldn_path = _compute_summary_table_from_lpd_productivity(
            lpd_vrt=lpd,
            **summary_table_stable_kwargs,
        )
    else:
        raise RuntimeError(f"Invalid prod_mode: {prod_mode!r}")

    summary_table_output_path = job_output_path.parent / f"{job_output_path.stem}.xlsx"
    save_summary_table(
        summary_table_output_path,
        summary_table,
        ldn_job.params.params["layer_lc_years"],
        ldn_job.params.params["layer_soc_years"],
    )
    ldn_job.end_date = dt.datetime.now(dt.timezone.utc)
    ldn_job.progress = 100
    ldn_job.results.bands.append(
        models.JobBand(
            name="SDG 15.3.1 Indicator",
            no_data_value=-32768.0,
            metadata={},
            activated=True
        )
    )
    ldn_job.results.local_paths = [
        output_ldn_path,
        summary_table_output_path
    ]
    return ldn_job


def _prepare_land_cover_file_paths(ldn_job: models.Job) -> typing.List[str]:
    lc_path = ldn_job.params.params["layer_lc_path"]
    lc_main_band_index = ldn_job.params.params["layer_lc_main_band_index"]
    lc_aux_band_indexes = ldn_job.params.params["layer_lc_aux_band_indexes"]
    lc_files = [
        utils.save_vrt(lc_path, lc_main_band_index)
    ]
    for lc_aux_band_index in lc_aux_band_indexes:
        lc_files.append(utils.save_vrt(lc_path, lc_aux_band_index))
    return lc_files


def _prepare_soil_organic_carbon_file_paths(
        ldn_job: models.Job) -> typing.List[str]:
    soc_path = ldn_job.params.params["layer_soc_path"]
    soc_main_band_index = ldn_job.params.params["layer_soc_main_band_index"]
    soc_aux_band_indexes = ldn_job.params.params["layer_soc_aux_band_indexes"]
    soc_files = [
        utils.save_vrt(soc_path, soc_main_band_index)
    ]
    for soc_aux_band_index in soc_aux_band_indexes:
        soc_files.append(utils.save_vrt(soc_path, soc_aux_band_index))
    return soc_files


def _prepare_trends_earth_mode_vrt_paths(
        ldn_job: models.Job) -> typing.Tuple[str, str, str]:
    traj_vrt_path = utils.save_vrt(
        ldn_job.params.params["layer_traj_path"],
        ldn_job.params.params["layer_traj_band_index"],
    )
    perf_vrt_path = utils.save_vrt(
        ldn_job.params.params["layer_perf_path"],
        ldn_job.params.params["layer_perf_band_index"],
    )
    state_vrt_path = utils.save_vrt(
        ldn_job.params.params["layer_state_path"],
        ldn_job.params.params["layer_state_band_index"],
    )
    return traj_vrt_path, perf_vrt_path, state_vrt_path


def _prepare_jrc_lpd_mode_vrt_path(
        ldn_job: models.Job) -> str:
    return utils.save_vrt(
        ldn_job.params.params["layer_lpd_path"],
        ldn_job.params.params["layer_lpd_band_index"],
    )


def _compute_summary_table_from_te_productivity(
        wkt_bounding_boxes,
        in_files,
        traj_vrt,
        perf_vrt,
        state_vrt,
        lc_band_nums,
        soc_band_nums,
        output_job_path: Path,
) -> typing.Tuple[SummaryTable, Path]:
    return _compute_ldn_summary_table(
        wkt_bounding_boxes=wkt_bounding_boxes,
        vrt_sources=in_files + [traj_vrt, perf_vrt, state_vrt],
        compute_bbs_from=traj_vrt,
        prod_mode=LdnProductivityMode.TRENDS_EARTH.value,
        lc_band_nums=lc_band_nums,
        soc_band_nums=soc_band_nums,
        output_job_path=output_job_path,
        prod_band_nums=np.arange(3) + 1 + soc_band_nums.max()
    )


def _compute_summary_table_from_lpd_productivity(
        wkt_bounding_boxes,
        in_files,
        lc_band_nums,
        soc_band_nums,
        lpd_vrt,
        output_job_path: Path,
) -> typing.Tuple[SummaryTable, Path]:
    return _compute_ldn_summary_table(
        wkt_bounding_boxes=wkt_bounding_boxes,
        vrt_sources=in_files + [lpd_vrt],
        compute_bbs_from=lpd_vrt,
        prod_mode=LdnProductivityMode.JRC_LPD.value,
        lc_band_nums=lc_band_nums,
        soc_band_nums=soc_band_nums,
        output_job_path=output_job_path,
        prod_band_nums=[max(soc_band_nums) + 1]
    )


def save_summary_table(
        output_path: Path,
        summary_table: SummaryTable,
        land_cover_years: typing.List[int],
        soil_organic_carbon_years: typing.List[int]
):
    """Save summary table into an xlsx file on disk"""
    template_summary_table_path = Path(
        __file__).parents[1] / "data/summary_table_ldn_sdg.xlsx"
    workbook = openpyxl.load_workbook(str(template_summary_table_path))
    _render_workbook(
        workbook, summary_table, land_cover_years, soil_organic_carbon_years)
    try:
        workbook.save(output_path)
        log(u'Indicator table saved to {}'.format(output_path))

    except IOError:
        error_message = (
            f"Error saving output table - check that {output_path!r} is accessible "
            f"and not already open."
        )
        log(error_message)


def _render_workbook(
        template_workbook,
        summary_table: SummaryTable,
        lc_years,
        soc_years,
):
    _write_overview_sdg_sheet(template_workbook["SDG 15.3.1"], summary_table)
    _write_productivity_sdg_sheet(template_workbook["Productivity"], summary_table)
    _write_soc_sdg_sheet(template_workbook["Soil organic carbon"], summary_table)
    _write_land_cover_sdg_sheet(template_workbook["Land cover"], summary_table)
    _write_unccd_reporting_sheet(
        template_workbook["UNCCD Reporting"], summary_table, lc_years, soc_years)
    return template_workbook


def _calculate_summary_table(
        bbox,
        pixel_aligned_bbox,
        vrt_sources,
        prod_band_nums,
        output_sdg_path: Path,
        prod_mode: str,
        lc_band_nums,
        soc_band_nums,
        mask_worker_process_name,
        deg_worker_process_name,
) -> typing.Tuple[
    typing.Optional[SummaryTable],
    str
]:
    # build vrt
    # Combines SDG 15.3.1 input raster into a VRT and crop to the AOI
    indic_vrt = tempfile.NamedTemporaryFile(suffix='.vrt').name
    log(u'Saving indicator VRT to: {}'.format(indic_vrt))
    # The plus one is because band numbers start at 1, not zero
    gdal.BuildVRT(
        indic_vrt,
        vrt_sources,
        outputBounds=pixel_aligned_bbox,
        resolution='highest',
        resampleAlg=gdal.GRA_NearestNeighbour,
        separate=True
    )

    # Compute a mask layer that will be used in the tabulation code to
    # mask out areas outside of the AOI. Do this instead of using
    # gdal.Clip to save having to clip and rewrite all of the layers in
    # the VRT
    mask_vrt = tempfile.NamedTemporaryFile(suffix='.tif').name
    log(u'Saving mask to {}'.format(mask_vrt))
    geojson = calculate.json_geom_to_geojson(
        qgis.core.QgsGeometry.fromWkt(bbox).asJson())
    deg_lc_mask_worker = worker.StartWorker(
        calculate.MaskWorker,
        mask_worker_process_name,
        mask_vrt,
        geojson,
        indic_vrt
    )
    error_message = ""
    if deg_lc_mask_worker.success:
        ######################################################################
        #  Calculate SDG 15.3.1 layers
        log('Calculating summary table...')
        deg_worker = worker.StartWorker(
            calculate_ldn.DegradationSummaryWorkerSDG,
            deg_worker_process_name,
            indic_vrt,
            prod_band_nums,
            prod_mode,
            str(output_sdg_path),
            lc_band_nums,
            soc_band_nums,
            mask_vrt
        )
        if not deg_worker.success:
            error_message = "Error calculating SDG 15.3.1 summary table."
            result = None

        else:
            raw_result = deg_worker.get_return()
            result = SummaryTable(
                soc_totals=raw_result[0],
                lc_totals=raw_result[1],
                trans_prod_xtab=raw_result[2],
                sdg_tbl_overall=raw_result[3],
                sdg_tbl_prod=raw_result[4],
                sdg_tbl_soc=raw_result[5],
                sdg_tbl_lc=raw_result[6]
            )
    else:
        result = None
        error_message = "Error creating mask."
    return result, error_message


def _compute_ldn_summary_table(
        wkt_bounding_boxes,
        vrt_sources,
        compute_bbs_from,
        prod_mode,
        lc_band_nums,
        soc_band_nums,
        output_job_path: Path,
        prod_band_nums,
) -> typing.Tuple[SummaryTable, Path]:
    """Computes summary table and the output tif file(s)"""
    bbs = areaofinterest.get_aligned_output_bounds(compute_bbs_from, wkt_bounding_boxes)
    output_name_pattern = {
        1: f"{output_job_path.stem}.tif",
        2: f"{output_job_path.stem}" + "_{index}.tif"
    }[len(wkt_bounding_boxes)]
    mask_name_fragment = {
        1: "Generating mask",
        2: "Generating mask (part {index} of 2)",
    }[len(wkt_bounding_boxes)]
    deg_name_fragment = {
        1: "Calculating summary table",
        2: "Calculating summary table (part {index} of 2)",
    }[len(wkt_bounding_boxes)]
    stable_kwargs = {
        "vrt_sources": vrt_sources,
        "prod_band_nums": prod_band_nums,
        "prod_mode": prod_mode,
        "lc_band_nums": lc_band_nums,
        "soc_band_nums": soc_band_nums,
    }
    output_path = output_job_path.parent / output_name_pattern.format(index=1)
    summary_table, error_message = _calculate_summary_table(
        bbox=wkt_bounding_boxes[0],
        pixel_aligned_bbox=bbs[0],
        output_sdg_path=output_path,
        mask_worker_process_name=mask_name_fragment.format(index=1),
        deg_worker_process_name=deg_name_fragment.format(index=1),
        **stable_kwargs
    )
    if summary_table is None:
        raise RuntimeError(error_message)
    if len(wkt_bounding_boxes) > 1:
        tile_output_path = output_job_path.parent / output_name_pattern.format(index=2)
        bbox2_summary_table, error_message = _calculate_summary_table(
            bbox=wkt_bounding_boxes[1],
            pixel_aligned_bbox=bbs[1],
            output_sdg_path=tile_output_path,
            mask_worker_process_name=mask_name_fragment.format(index=2),
            deg_worker_process_name=deg_name_fragment.format(index=2),
            **stable_kwargs
        )
        if bbox2_summary_table is None:
            raise RuntimeError(error_message)
        summary_table = _accumulate_bounding_boxes_summary_tables(
            summary_table, bbox2_summary_table)
        output_path = output_job_path.parent / f"{output_job_path.stem}.vrt"
    return summary_table, output_path


def _accumulate_bounding_boxes_summary_tables(
        first: SummaryTable, second: SummaryTable) -> SummaryTable:
    for n in range(len(first.soc_totals)):
        first.soc_totals[n] = calculate_ldn.merge_area_tables(
            first.soc_totals[n],
            second.soc_totals[n]
        )
    first.lc_totals += second.lc_totals
    if second.trans_prod_xtab[0][0].size != 0:
        first.trans_prod_xtab = calculate_ldn.merge_xtabs(
            first.trans_prod_xtab[0],
            first.trans_prod_xtab[1],
            first.trans_prod_xtab[2],
            second.trans_prod_xtab[0],
            second.trans_prod_xtab[1],
            second.trans_prod_xtab[2]
        )
    first.sdg_tbl_overall += second.sdg_tbl_overall
    first.sdg_tbl_prod += second.sdg_tbl_prod
    first.sdg_tbl_soc += second.sdg_tbl_soc
    first.sdg_tbl_lc += second.sdg_tbl_lc
    return first


def _maybe_add_image_to_sheet(image_filename: str, sheet):
    try:
        image_path = Path(__file__).parents[1] / "data" / image_filename
        logo = Image(image_path)
        sheet.add_image(logo, 'H1')
    except ImportError:
        # add_image will fail on computers without PIL installed (this will be
        # an issue on some Macs, likely others). it is only used here to add
        # our logo, so no big deal.
        pass


def _write_overview_sdg_sheet(sheet, summary_table: SummaryTable):
    summary.write_table_to_sheet(
        sheet, np.transpose(summary_table.sdg_tbl_overall), 6, 6)
    _maybe_add_image_to_sheet("trends_earth_logo_bl_300width.png", sheet)


def _write_productivity_sdg_sheet(sheet, summary_table: SummaryTable):
    summary.write_table_to_sheet(
        sheet, np.transpose(summary_table.sdg_tbl_prod), 6, 6)
    summary.write_table_to_sheet(
        sheet, _get_prod_table(summary_table.trans_prod_xtab, 5), 16, 3)
    summary.write_table_to_sheet(
        sheet, _get_prod_table(summary_table.trans_prod_xtab, 4), 28, 3)
    summary.write_table_to_sheet(
        sheet, _get_prod_table(summary_table.trans_prod_xtab, 3), 40, 3)
    summary.write_table_to_sheet(
        sheet, _get_prod_table(summary_table.trans_prod_xtab, 2), 52, 3)
    summary.write_table_to_sheet(
        sheet, _get_prod_table(summary_table.trans_prod_xtab, 1), 64, 3)
    summary.write_table_to_sheet(
        sheet, _get_prod_table(summary_table.trans_prod_xtab, -32768), 76, 3)
    _maybe_add_image_to_sheet("trends_earth_logo_bl_300width.png", sheet)


def _write_soc_sdg_sheet(sheet, summary_table: SummaryTable):
    summary.write_table_to_sheet(sheet, np.transpose(summary_table.sdg_tbl_soc), 6, 6)
    # First write baseline
    summary.write_table_to_sheet(
        sheet,
        _get_soc_total_by_class(
            summary_table.trans_prod_xtab, summary_table.soc_totals[0]),
        16,
        3
    )
    # Now write target
    summary.write_table_to_sheet(
        sheet,
        _get_soc_total_by_class(
            summary_table.trans_prod_xtab, summary_table.soc_totals[-1]),
        16,
        4
    )

    # Write table of baseline areas
    lc_trans_table_no_water = _get_lc_table(
        summary_table.trans_prod_xtab, classes=np.arange(1, 6 + 1))
    summary.write_table_to_sheet(
        sheet, np.reshape(np.sum(lc_trans_table_no_water, 1), (-1, 1)), 16, 5)
    # Write table of target areas
    summary.write_table_to_sheet(
        sheet, np.reshape(np.sum(lc_trans_table_no_water, 0), (-1, 1)), 16, 6)

    # write_soc_stock_change_table has its own writing function as it needs to write a
    # mix of numbers and strings
    _write_soc_stock_change_table(
        sheet, 27, 3, summary_table.soc_totals[0], summary_table.soc_totals[-1])
    _maybe_add_image_to_sheet("trends_earth_logo_bl_300width.png", sheet)


def _write_land_cover_sdg_sheet(sheet, summary_table: SummaryTable):
    summary.write_table_to_sheet(sheet, np.transpose(summary_table.sdg_tbl_lc), 6, 6)
    summary.write_table_to_sheet(
        sheet, _get_lc_table(summary_table.trans_prod_xtab), 26, 3)
    _maybe_add_image_to_sheet("trends_earth_logo_bl_300width.png", sheet)


def _write_unccd_reporting_sheet(
        sheet, summary_table: SummaryTable, land_cover_years, soil_organic_carbon_years):

    for i in range(len(land_cover_years)):
        log('lc_years len: {}'.format(len(land_cover_years)))
        # Water bodies
        cell = sheet.cell(5 + i, 4)
        cell.value = summary_table.lc_totals[i][6]
        # Other classes
        summary.write_row_to_sheet(
            sheet,
            np.append(land_cover_years[i], summary_table.lc_totals[i][0:6]),
            38 + i,
            2
        )

    summary.write_table_to_sheet(
        sheet, _get_lpd_table(summary_table.trans_prod_xtab), 82, 3)

    for i in range(len(soil_organic_carbon_years)):
        summary.write_row_to_sheet(
            sheet,
            np.append(
                soil_organic_carbon_years[i],
                _get_soc_total_by_class(
                    summary_table.trans_prod_xtab,
                    summary_table.soc_totals[i],
                    uselog=True
                )
            ),
            92 + i,
            2
        )
    _maybe_add_image_to_sheet("trends_earth_logo_bl_300width.png", sheet)


def _get_prod_table(table, prod_class, classes=list(range(1, 7 + 1))):
    out = np.zeros((len(classes), len(classes)))
    for bl_class in range(len(classes)):
        for tg_class in range(len(classes)):
            transition = int('{}{}'.format(classes[bl_class], classes[tg_class]))
            out[bl_class, tg_class] = summary.get_xtab_area(
                table, prod_class, transition)
    return out


def _get_soc_total_by_class(
        trans_prod_xtab,
        soc_totals,
        classes=list(range(1, 6 + 1)),
        uselog=False
):
    # Note classes for this function go from 1-6 to exclude water from the SOC
    # totals
    out = np.zeros((len(classes), 1))
    for row in range(len(classes)):
        area = 0
        soc = 0
        # Need to sum up the total soc across the pixels and then divide by
        # total area
        for n in range(len(classes)):
            trans = int('{}{}'.format(classes[row], classes[n]))
            area += summary.get_xtab_area(trans_prod_xtab, None, trans)
            soc += _get_soc_total(soc_totals, trans)

        # Note areas are in sq km. Need to convert to ha
        if soc != 0 and area != 0:
            out[row][0] = soc / (area * 100)
        else:
            out[row][0]
    return out


def _get_lc_table(table, classes=list(range(1, 7 + 1))):
    out = np.zeros((len(classes), len(classes)))
    for bl_class in range(len(classes)):
        for tg_class in range(len(classes)):
            transition = int('{}{}'.format(classes[bl_class], classes[tg_class]))
            out[bl_class, tg_class] = summary.get_xtab_area(table, None, transition)
    return out


def _write_soc_stock_change_table(
        sheet, first_row, first_col, soc_bl_totals,
        soc_tg_totals, classes=list(range(1, 6 + 1))
):
    # Note classes for this function go from 1-6 to exclude water from the SOC
    # totals
    for row in range(len(classes)):
        for col in range(len(classes)):
            cell = sheet.cell(row=row + first_row, column=col + first_col)
            transition = int('{}{}'.format(classes[row], classes[col]))
            bl_soc = _get_soc_total(soc_bl_totals, transition)
            tg_soc = _get_soc_total(soc_tg_totals, transition)
            try:
                cell.value = (tg_soc - bl_soc) / bl_soc
            except ZeroDivisionError:
                cell.value = ''


def _get_lpd_table(
        table,
        lc_classes=list(range(1, 6 + 1)),  # Don't include water bodies in the table
        lpd_classes=[1, 2, 3, 4, 5, -32768]
):
    out = np.zeros((len(lc_classes), len(lpd_classes)))
    for lc_class_num in range(len(lc_classes)):
        for prod_num in range(len(lpd_classes)):
            transition = int(
                '{}{}'.format(lc_classes[lc_class_num], lc_classes[lc_class_num])
            )
            out[lc_class_num, prod_num] = summary.get_xtab_area(
                table, lpd_classes[prod_num], transition)
    return out


def _get_soc_total(soc_table, transition):
    ind = np.where(soc_table[0] == transition)[0]
    if ind.size == 0:
        return 0
    else:
        return float(soc_table[1][ind])
