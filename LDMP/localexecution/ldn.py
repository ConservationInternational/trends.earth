import os
import dataclasses
import datetime as dt
import enum
import json
import tempfile
import typing
from pathlib import Path

from PyQt5 import QtWidgets

import numpy as np
import openpyxl
from osgeo import (
    gdal,
    osr,
)
import qgis.core

from te_schemas import (
    schemas,
    land_cover,
    reporting
)

from .. import (
    areaofinterest,
    calculate,
    calculate_ldn,
    data_io,
    summary,
    tr,
    utils,
    worker,
    __version__,
    __revision__,
    __release_date__
)
from ..jobs import (
    models,
)
from ..logger import log


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
class SummaryTableWidgets:
    '''Combo boxes and methods used in the SDG 15.3.1 summary table widget'''
    combo_datasets: data_io.WidgetDataIOSelectTEDatasetExisting
    combo_layer_traj: data_io.WidgetDataIOSelectTELayerExisting
    combo_layer_perf: data_io.WidgetDataIOSelectTELayerExisting
    combo_layer_state: data_io.WidgetDataIOSelectTELayerExisting
    combo_layer_lpd: data_io.WidgetDataIOSelectTELayerImport
    combo_layer_lc: data_io.WidgetDataIOSelectTELayerExisting
    combo_layer_soc: data_io.WidgetDataIOSelectTELayerExisting
    radio_te_prod: QtWidgets.QRadioButton
    radio_lpd_jrc: QtWidgets.QRadioButton

    def __post_init__(self):
        self.radio_lpd_jrc.toggled.connect(self.radio_lpd_jrc_toggled)
        self.radio_lpd_jrc_toggled()
        self.combo_datasets.job_selected.connect(self.set_combo_selections_from_job_id)

    def populate(self):
        self.combo_datasets.populate()
        self.populate_layer_combo_boxes()

    def radio_lpd_jrc_toggled(self):
        if self.radio_lpd_jrc.isChecked():
            self.combo_layer_lpd.setEnabled(True)
            self.combo_layer_traj.setEnabled(False)
            self.combo_layer_perf.setEnabled(False)
            self.combo_layer_state.setEnabled(False)
        else:
            self.combo_layer_lpd.setEnabled(False)
            self.combo_layer_traj.setEnabled(True)
            self.combo_layer_perf.setEnabled(True)
            self.combo_layer_state.setEnabled(True)

    def populate_layer_combo_boxes(self):
        self.combo_layer_lpd.populate()
        self.combo_layer_traj.populate()
        self.combo_layer_perf.populate()
        self.combo_layer_state.populate()
        self.combo_layer_lc.populate()
        self.combo_layer_soc.populate()

    def set_combo_selections_from_job_id(self, job_id):
        self.combo_layer_lpd.set_index_from_job_id(job_id)
        self.combo_layer_traj.set_index_from_job_id(job_id)
        self.combo_layer_perf.set_index_from_job_id(job_id)
        self.combo_layer_state.set_index_from_job_id(job_id)
        self.combo_layer_lc.set_index_from_job_id(job_id)
        self.combo_layer_soc.set_index_from_job_id(job_id)


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
    traj_year_initial = None
    traj_year_final = None
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
        traj_year_initial = traj_band_info.band_info.metadata['year_start']
        traj_year_final = traj_band_info.band_info.metadata['year_end']
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
        "layer_lc_trans_matrix": land_cover_input_paths.main_band.metadata['trans_matrix'],
        "layer_lc_nesting": land_cover_input_paths.main_band.metadata['nesting'],
        "layer_soc_path": str(soil_organic_carbon_input_paths.path),
        "layer_soc_main_band_index": soil_organic_carbon_input_paths.main_band_index,
        "layer_soc_aux_band_indexes": soil_organic_carbon_input_paths.aux_band_indexes,
        "layer_soc_years": soil_organic_carbon_input_paths.years,
        "layer_soc_trans_matrix": soil_organic_carbon_input_paths.main_band.metadata['trans_matrix'],
        "layer_soc_nesting": soil_organic_carbon_input_paths.main_band.metadata['nesting'],
        "layer_traj_path": traj_path,
        "layer_traj_band_index": traj_index,
        "layer_traj_year_initial": traj_year_initial,
        "layer_traj_year_final": traj_year_final,
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
        ldn_job: models.Job,
        area_of_interest: areaofinterest.AOI) -> models.Job:
    """Calculate final SDG 15.3.1 indicator and save its outputs to disk too."""

    job_output_path, _ = utils.get_local_job_output_paths(ldn_job)

    summary_table_stable_kwargs = {}

    for period, period_params in ldn_job.params.params.items():
        lc_files = _prepare_land_cover_file_paths(period_params)
        lc_band_nums = np.arange(len(lc_files)) + 1
        soc_files = _prepare_soil_organic_carbon_file_paths(period_params)
        soc_band_nums = np.arange(len(lc_files)) + 1 + lc_band_nums.max()
        sub_job_output_path = job_output_path.parent / f"{job_output_path.stem}_{period}.json"
        _, wkt_bounding_boxes = area_of_interest.meridian_split("layer", "wkt", warn=False)
        prod_mode = period_params["prod_mode"]

        if 'period' not in period_params:
            # Add in period start/end if it isn't already in the parameters
            # (wouldn't be if these layers were all run individually and not
            # with the all-in-one tool)

            if prod_mode == LdnProductivityMode.TRENDS_EARTH.value:
                period_params["prod_year_start"] = period_params['layer_traj_year_initial']
                period_params["prod_year_final"] = period_params['layer_traj_year_final']
                period_params["period"] = {
                    "name": period,
                    "year_start": period_params['layer_traj_year_initial'],
                    "year_final": period_params['layer_traj_year_final'],
                }
                log('added period_params year data for TE')
            else:
                period_params["prod_year_start"] = 1999
                period_params["prod_year_final"] = 2013
                period_params["period"] = {
                    "name": period,
                    "year_start": 1999,  # TODO: fix this when new JRC added, and don't hardcode
                    "year_final": 2013  # TODO: fix this when new JRC added, and don't hardcode
                }
        summary_table_stable_kwargs[period] = {
            "wkt_bounding_boxes": wkt_bounding_boxes,
            "in_files": lc_files + soc_files,
            "lc_band_nums": lc_band_nums,
            "lc_legend_nesting": land_cover.LCLegendNesting.Schema().loads(period_params["layer_lc_nesting"]),
            "lc_trans_matrix": land_cover.LCTransitionDefinitionDeg.Schema().loads(period_params["layer_lc_trans_matrix"]),
            "soc_band_nums": soc_band_nums,
            "soc_legend_nesting": land_cover.LCLegendNesting.Schema().loads(period_params["layer_soc_nesting"]),
            "soc_trans_matrix": land_cover.LCTransitionDefinitionDeg.Schema().loads(period_params["layer_soc_trans_matrix"]),
            "output_job_path": sub_job_output_path,
        }

        if prod_mode == LdnProductivityMode.TRENDS_EARTH.value:
            traj, perf, state = _prepare_trends_earth_mode_vrt_paths(period_params)
            summary_table, output_ldn_path = _compute_summary_table_from_te_productivity(
                traj_vrt=traj,
                perf_vrt=perf,
                state_vrt=state,
                **summary_table_stable_kwargs[period]
            )
        elif prod_mode == LdnProductivityMode.JRC_LPD.value:
            lpd = _prepare_jrc_lpd_mode_vrt_path(period_params)
            summary_table, output_ldn_path = _compute_summary_table_from_lpd_productivity(
                lpd_vrt=lpd,
                **summary_table_stable_kwargs[period],
            )
        else:
            raise RuntimeError(f"Invalid prod_mode: {prod_mode!r}")

        ldn_job.results.bands.append(
            models.JobBand(
                name="SDG 15.3.1 Indicator",
                no_data_value=-32768.0,
                metadata={
                    'year_start': period_params['period']['year_start'],
                    'year_final': period_params['period']['year_final'],
                },
                activated=True
            )
        )

        summary_table_output_path = sub_job_output_path.parent / f"{job_output_path.stem}.xlsx"
        save_summary_table(
            summary_table_output_path,
            summary_table,
            period_params["layer_lc_years"],
            period_params["layer_soc_years"],
        )

        ldn_job.results.local_paths = [
            output_ldn_path,
            summary_table_output_path
        ]

    summary_json_output_path = job_output_path.parent / f"{job_output_path.stem}_reporting.json"
    save_reporting_json(
        summary_json_output_path,
        summary_table,
        ldn_job.params.params,
        ldn_job.params.task_name,
        area_of_interest,
        summary_table_stable_kwargs
    )
    ldn_job.end_date = dt.datetime.now(dt.timezone.utc)
    ldn_job.progress = 100

    return ldn_job


def _prepare_land_cover_file_paths(params: typing.Dict) -> typing.List[str]:
    lc_path = params["layer_lc_path"]
    lc_main_band_index = params["layer_lc_main_band_index"]
    lc_aux_band_indexes = params["layer_lc_aux_band_indexes"]
    lc_files = [
        utils.save_vrt(lc_path, lc_main_band_index)
    ]

    for lc_aux_band_index in lc_aux_band_indexes:
        lc_files.append(utils.save_vrt(lc_path, lc_aux_band_index))

    return lc_files


def _prepare_soil_organic_carbon_file_paths(
    params: typing.Dict
) -> typing.List[str]:
    soc_path = params["layer_soc_path"]
    soc_main_band_index = params["layer_soc_main_band_index"]
    soc_aux_band_indexes = params["layer_soc_aux_band_indexes"]
    soc_files = [
        utils.save_vrt(soc_path, soc_main_band_index)
    ]

    for soc_aux_band_index in soc_aux_band_indexes:
        soc_files.append(utils.save_vrt(soc_path, soc_aux_band_index))

    return soc_files


def _prepare_trends_earth_mode_vrt_paths(
    params: typing.Dict
) -> typing.Tuple[str, str, str]:
    traj_vrt_path = utils.save_vrt(
        params["layer_traj_path"],
        params["layer_traj_band_index"],
    )
    perf_vrt_path = utils.save_vrt(
        params["layer_perf_path"],
        params["layer_perf_band_index"],
    )
    state_vrt_path = utils.save_vrt(
        params["layer_state_path"],
        params["layer_state_band_index"],
    )

    return traj_vrt_path, perf_vrt_path, state_vrt_path


def _prepare_jrc_lpd_mode_vrt_path(
    params: typing.Dict
) -> str:
    return utils.save_vrt(
        params["layer_lpd_path"],
        params["layer_lpd_band_index"],
    )


def _compute_summary_table_from_te_productivity(
        wkt_bounding_boxes,
        in_files,
        traj_vrt,
        perf_vrt,
        state_vrt,
        lc_band_nums,
        lc_legend_nesting: land_cover.LCLegendNesting,
        lc_trans_matrix: land_cover.LCTransitionDefinitionDeg,
        soc_band_nums,
        soc_legend_nesting: land_cover.LCLegendNesting,
        soc_trans_matrix: land_cover.LCTransitionDefinitionDeg,
        output_job_path: Path,
) -> typing.Tuple[SummaryTable, Path]:
    '''Compute summary table if a trends.earth productivity dataset is used'''

    return _compute_ldn_summary_table(
        wkt_bounding_boxes=wkt_bounding_boxes,
        vrt_sources=in_files + [traj_vrt, perf_vrt, state_vrt],
        compute_bbs_from=traj_vrt,
        prod_mode=LdnProductivityMode.TRENDS_EARTH.value,
        lc_band_nums=lc_band_nums,
        soc_band_nums=soc_band_nums,
        output_job_path=output_job_path,
        prod_band_nums=np.arange(3) + 1 + soc_band_nums.max(),
        lc_legend_nesting=lc_legend_nesting,
        lc_trans_matrix=lc_trans_matrix,
    )


def _compute_summary_table_from_lpd_productivity(
        wkt_bounding_boxes,
        in_files,
        lc_band_nums,
        lc_legend_nesting: land_cover.LCLegendNesting,
        lc_trans_matrix: land_cover.LCTransitionDefinitionDeg,
        soc_band_nums,
        soc_legend_nesting: land_cover.LCLegendNesting,
        soc_trans_matrix: land_cover.LCTransitionDefinitionDeg,
        lpd_vrt,
        output_job_path: Path,
) -> typing.Tuple[SummaryTable, Path]:
    '''Compute summary table if a JRC LPD productivity dataset is used'''

    return _compute_ldn_summary_table(
        wkt_bounding_boxes=wkt_bounding_boxes,
        vrt_sources=in_files + [lpd_vrt],
        compute_bbs_from=lpd_vrt,
        prod_mode=LdnProductivityMode.JRC_LPD.value,
        lc_band_nums=lc_band_nums,
        soc_band_nums=soc_band_nums,
        output_job_path=output_job_path,
        prod_band_nums=[max(soc_band_nums) + 1],
        lc_legend_nesting=lc_legend_nesting,
        lc_trans_matrix=lc_trans_matrix,
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
    _render_ldn_workbook(
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


def save_reporting_json(
        output_path: Path,
        summary_table: SummaryTable,
        params: dict,
        task_name: str,
        aoi: areaofinterest.AOI,
        summary_table_kwargs: dict):

    land_condition_reports = {}

    for period, period_params in params.items():
        ##########################################################################
        # Area summary tables
        lc_legend_nesting = summary_table_kwargs[period]['lc_legend_nesting']
        lc_trans_matrix = summary_table_kwargs[period]['lc_trans_matrix']

        sdg_tbl_overall = reporting.AreaList('SDG Indicator 15.3.1', 'sq km',
                [reporting.Area('Improved', summary_table.sdg_tbl_overall[0, 0]),
                 reporting.Area('Stable', summary_table.sdg_tbl_overall[0, 1]),
                 reporting.Area('Degraded', summary_table.sdg_tbl_overall[0, 2]),
                 reporting.Area('No data', summary_table.sdg_tbl_overall[0, 3])])

        sdg_tbl_prod = reporting.AreaList('Productivity', 'sq km',
                [reporting.Area('Improved', summary_table.sdg_tbl_prod[0, 0]),
                 reporting.Area('Stable', summary_table.sdg_tbl_prod[0, 1]),
                 reporting.Area('Degraded', summary_table.sdg_tbl_prod[0, 2]),
                 reporting.Area('No data', summary_table.sdg_tbl_prod[0, 3])])

        sdg_tbl_soc = reporting.AreaList('Soil organic carbon', 'sq km',
                [reporting.Area('Improved', summary_table.sdg_tbl_soc[0, 0]),
                 reporting.Area('Stable', summary_table.sdg_tbl_soc[0, 1]),
                 reporting.Area('Degraded', summary_table.sdg_tbl_soc[0, 2]),
                 reporting.Area('No data', summary_table.sdg_tbl_soc[0, 3])])

        sdg_tbl_lc = reporting.AreaList('Land cover', 'sq km',
                [reporting.Area('Improved', summary_table.sdg_tbl_lc[0, 0]),
                 reporting.Area('Stable', summary_table.sdg_tbl_lc[0, 1]),
                 reporting.Area('Degraded', summary_table.sdg_tbl_lc[0, 2]),
                 reporting.Area('No data', summary_table.sdg_tbl_lc[0, 3])])


        #######################################################################
        # Productivity tables

        #TODO: Remove these hardcoded values
        classes = ['Tree-covered',
                   'Grassland',
                   'Cropland',
                   'Wetland',
                   'Artificial',
                   'Other land',
                   'Water body']
        class_codes = list(range(len(classes)))

        crosstab_prod = []

        for name, code in zip(['Increasing',
                               'Stable',
                               'Stressed',
                               'Moderate decline',
                               'Declining',
                               'No data'],
                              [5, 4, 3, 2, 1, -32768]):
            crosstab_prod.append(
                reporting.CrossTab(name,
                    unit='sq km',
                    initial_year=period_params["prod_year_start"],
                    final_year=period_params["prod_year_final"],
                    values=[
                        reporting.CrossTabEntry(
                            classes[i],
                            classes[j],
                            value=_get_prod_table(
                                summary_table.trans_prod_xtab, code)[i, j]
                        ) for i in range(len(classes)) for j in range(len(classes))
                    ]
                )
            )

        #######################################################################
        # Land cover tables

        land_cover_years = period_params["layer_lc_years"]

        ###
        # LC transition cross tab
        lc_table = _get_lc_table(summary_table.trans_prod_xtab)
        lc_by_transition_type = []
        for i in range(0, len(classes) - 1):
            for f in range(0, len(classes) - 1):
                lc_by_transition_type.append(
                    reporting.CrossTabEntry(
                        classes[i],
                        classes[f],
                        value=lc_table[i, f]
                    )
                )
        lc_by_transition_type = sorted(
            lc_by_transition_type,
            key=lambda i: i.value,
            reverse=True
        )

        crosstab_lc = reporting.CrossTab(
            name='Land area by land cover transition type',
            unit='sq km',
            initial_year=int(land_cover_years[0]),
            final_year=int(land_cover_years[-1]),
            # TODO: Check indexing as may be missing a class
            values=lc_by_transition_type
        )

        ###
        # LC by year
        lc_by_year = {}

        for i in range(len(land_cover_years)):
            year = int(land_cover_years[i])
            lc_by_year[year] = {
                classes[j]: summary_table.lc_totals[i][j] for j in range(len(classes))
            }
        lc_by_year_by_class = reporting.ValuesByYearDict(
            name='Area by year by land cover class',
            unit='sq km',
            values=lc_by_year
        )

        #######################################################################
        # Soil organic carbon tables

        soil_organic_carbon_years = period_params["layer_soc_years"]

        # ###
        # # SOC by transition type (fraction of initial stock)
        # soc_by_transition_fraction = []
        # for i in range(1, len(classes) - 1):
        #     for f in range(1, len(classes) - 1):
        #         transition = int('{}{}'.format(i, f))
        #         bl_soc = _get_soc_total(summary_table.soc_totals[0], transition)
        #         tg_soc = _get_soc_total(summary_table.soc_totals[-1], transition)
        #         try:
        #             fraction = (tg_soc - bl_soc) / bl_soc
        #         except ZeroDivisionError:
        #             fraction = None
        #         soc_by_transition_fraction.append(
        #             reporting.CrossTabEntry(
        #                 classes[i],
        #                 classes[f],
        #                 value=fraction
        #             )
        #         )
        # crosstab_soc_by_transition_fraction = reporting.CrossTab(
        #     'Fraction of initial carbon stock remaining, by transition type',
        #     unit='fraction',
        #     initial_year=soil_organic_carbon_years[0],
        #     final_year=soil_organic_carbon_years[-1],
        #     values=soc_by_transition_fraction
        # )

        ###
        # SOC by transition type (initial and final stock for each transition
        # type)
        soc_by_transition = []
        for i in range(1, len(classes) - 1):
            for f in range(1, len(classes) - 1):
                transition = int('{}{}'.format(i, f))
                soc_by_transition.append(
                    reporting.CrossTabEntryInitialFinal(
                        initial_label=classes[i],
                        final_label=classes[f],
                        initial_value=_get_soc_total(summary_table.soc_totals[0], transition),
                        final_value=_get_soc_total(summary_table.soc_totals[-1], transition)
                    )
                )
        crosstab_soc_by_transition_per_ha = reporting.CrossTab(
            name='Initial and final carbon stock by transition type',
            unit='tons / ha',
            initial_year=soil_organic_carbon_years[0],
            final_year=soil_organic_carbon_years[-1],
            values=soc_by_transition
        )

        ###
        # SOC by year by land cover class
        soc_by_year = {}

        for i in range(len(soil_organic_carbon_years)):
            year = int(soil_organic_carbon_years[i])
            soc_by_year[year] = {
                classes[j]:_get_soc_total_by_class(
                    summary_table.
                    trans_prod_xtab,
                    summary_table.soc_totals[i], classes=class_codes).transpose()[0][j] for j in range(len(classes))
            }
        soc_by_year_by_class = reporting.ValuesByYearDict(
            name='Soil organic carbon by year by land cover class',
            unit='tonnes per hectare',
            values=soc_by_year
        )

        land_condition_reports[period] =  reporting.LandConditionReport(
            sdg=reporting.SDG15Report(summary=sdg_tbl_overall),

            productivity=reporting.ProductivityReport(
                summary=sdg_tbl_prod,
                crosstabs_by_productivity_class=crosstab_prod),

            land_cover=reporting.LandCoverReport(
                summary=sdg_tbl_lc,
                legend_nesting=lc_legend_nesting,
                transition_matrix=lc_trans_matrix,
                crosstab_by_land_cover_class=crosstab_lc,
                land_cover_areas_by_year=lc_by_year_by_class),

            soil_organic_carbon=reporting.SoilOrganicCarbonReport(
                summary=sdg_tbl_soc,
                crosstab_by_land_cover_class=crosstab_soc_by_transition_per_ha,
                soc_stock_by_year=soc_by_year_by_class)
        )

    ##########################################################################
    # Format final JSON output
    te_summary = reporting.TrendsEarthSummary(
            metadata=reporting.ReportMetadata(
                title='Trends.Earth Summary Report',
                date=dt.datetime.now(dt.timezone.utc),

                trends_earth_version=schemas.TrendsEarthVersion(
                    version=__version__,
                    revision=__revision__,
                    release_date=dt.datetime.strptime(__release_date__,'%Y/%m/%d %H:%M:%SZ')),

                area_of_interest=schemas.AreaOfInterest(
                    name=task_name, #TODO replace this with area of interest name once implemented in TE
                    geojson=aoi.get_geojson(),
                    crs_wkt=aoi.get_crs_wkt()
                    )
            ),

            land_condition=land_condition_reports,

            affected_population={},

            drought={}
        )

    try:
        te_summary_json = json.loads(reporting.TrendsEarthSummary.Schema().dumps(te_summary))
        with open(output_path, 'w') as f:
            json.dump(te_summary_json, f, indent=4)

        return True

    except IOError:
        log(u'Error saving {}'.format(output_path))
        QtWidgets.QMessageBox.critical(None,
                tr("Error"),
                tr(u"Error saving indicator table JSON - check that {} is accessible and not already open.".format(output_path)))

        return False


class DegradationSummaryWorkerSDG(worker.AbstractWorker):
    def __init__(self,
                 src_file,
                 prod_band_nums,
                 prod_mode,
                 prod_out_file,
                 lc_band_nums,
                 soc_band_nums,
                 mask_file,
                 nesting: land_cover.LCLegendNesting,
                 trans_matrix: land_cover.LCTransitionDefinitionDeg):

        worker.AbstractWorker.__init__(self)

        self.src_file = src_file
        self.prod_band_nums = [int(x) for x in prod_band_nums]
        self.prod_mode = prod_mode
        self.prod_out_file = prod_out_file
        # Note the first entry in the lc_band_nums, and soc_band_nums lists is
        # the degradation layer for that dataset
        self.lc_band_nums = [int(x) for x in lc_band_nums]
        self.soc_band_nums = [int(x) for x in soc_band_nums]
        self.mask_file = mask_file
        self.nesting = nesting
        self.trans_matrix = trans_matrix

    def work(self):
        self.toggle_show_progress.emit(True)
        self.toggle_show_cancel.emit(True)

        src_ds = gdal.Open(self.src_file)

        band_lc_deg = src_ds.GetRasterBand(self.lc_band_nums[0])
        band_lc_bl = src_ds.GetRasterBand(self.lc_band_nums[1])
        band_lc_tg = src_ds.GetRasterBand(self.lc_band_nums[-1])
        band_soc_deg = src_ds.GetRasterBand(self.soc_band_nums[0])

        mask_ds = gdal.Open(self.mask_file)
        band_mask = mask_ds.GetRasterBand(1)

        if self.prod_mode == 'Trends.Earth productivity':
            traj_band = src_ds.GetRasterBand(self.prod_band_nums[0])
            perf_band = src_ds.GetRasterBand(self.prod_band_nums[1])
            state_band = src_ds.GetRasterBand(self.prod_band_nums[2])
            block_sizes = traj_band.GetBlockSize()
            xsize = traj_band.XSize
            ysize = traj_band.YSize
            # Save the combined productivity indicator as well, in the second
            # layer in the deg file
            n_out_bands = 2
        else:
            lpd_band = src_ds.GetRasterBand(self.prod_band_nums[0])
            block_sizes = band_lc_deg.GetBlockSize()
            xsize = band_lc_deg.XSize
            ysize = band_lc_deg.YSize
            n_out_bands = 1

        x_block_size = block_sizes[0]
        y_block_size = block_sizes[1]

        # Setup output file for SDG degradation indicator and combined
        # productivity bands
        driver = gdal.GetDriverByName("GTiff")
        dst_ds_deg = driver.Create(self.prod_out_file, xsize, ysize, n_out_bands,
                                   gdal.GDT_Int16, options=['COMPRESS=LZW'])
        src_gt = src_ds.GetGeoTransform()
        dst_ds_deg.SetGeoTransform(src_gt)
        dst_srs = osr.SpatialReference()
        dst_srs.ImportFromWkt(src_ds.GetProjectionRef())
        dst_ds_deg.SetProjection(dst_srs.ExportToWkt())

        # Width of cells in longitude
        long_width = src_gt[1]
        # Set initial lat ot the top left corner latitude
        lat = src_gt[3]
        # Width of cells in latitude
        pixel_height = src_gt[5]

        # utils.log('long_width: {}'.format(long_width))
        # utils.log('lat: {}'.format(lat))
        # utils.log('pixel_height: {}'.format(pixel_height))

        xt = None
        # The first array in each row stores transitions, the second stores SOC
        # totals for each transition
        soc_totals_table = [[np.array([], dtype=np.int16), np.array([], dtype=np.float32)] for i in
                            range(len(self.soc_band_nums) - 1)]
        # TODO: Source the size of the lc_totals_table from the size of the
        # legend in self.nesting
        # The 8 below is for eight classes plus no data, and the minus one is
        # because one of the bands is a degradation layer
        lc_totals_table = np.zeros((len(self.lc_band_nums) - 1, 8))
        sdg_tbl_overall = np.zeros((1, 4))
        sdg_tbl_prod = np.zeros((1, 4))
        sdg_tbl_soc = np.zeros((1, 4))
        sdg_tbl_lc = np.zeros((1, 4))

        # pr = cProfile.Profile()
        # pr.enable()

        blocks = 0

        for y in range(0, ysize, y_block_size):
            if y + y_block_size < ysize:
                rows = y_block_size
            else:
                rows = ysize - y

            for x in range(0, xsize, x_block_size):
                if self.killed:
                    log("Processing killed by user after processing {} out of {} blocks.".format(y, ysize))

                    break
                self.progress.emit(100 * (float(y) + (float(x) / xsize) * y_block_size) / ysize)

                if x + x_block_size < xsize:
                    cols = x_block_size
                else:
                    cols = xsize - x

                mask_array = band_mask.ReadAsArray(x, y, cols, rows)

                # Calculate cell area for each horizontal line
                # utils.log('y: {}'.format(y))
                # utils.log('x: {}'.format(x))
                # utils.log('rows: {}'.format(rows))
                cell_areas = np.array(
                    [summary.calc_cell_area(lat + pixel_height * n, lat + pixel_height * (n + 1), long_width) for n in
                     range(rows)])
                cell_areas.shape = (cell_areas.size, 1)
                # Make an array of the same size as the input arrays containing
                # the area of each cell (which is identical for all cells ina
                # given row - cell areas only vary among rows)
                cell_areas_array = np.repeat(cell_areas, cols, axis=1).astype(np.float32)

                if self.prod_mode == 'Trends.Earth productivity':
                    traj_recode = calculate.ldn_recode_traj(
                        traj_band.ReadAsArray(x, y, cols, rows))

                    state_recode = calculate.ldn_recode_state(
                        state_band.ReadAsArray(x, y, cols, rows))

                    perf_array = perf_band.ReadAsArray(x, y, cols, rows)
                    prod5 = calculate.ldn_make_prod5(
                        traj_recode, state_recode, perf_array, mask_array)

                    # Save combined productivity indicator for later visualization
                    dst_ds_deg.GetRasterBand(2).WriteArray(prod5, x, y)
                else:
                    lpd_array = lpd_band.ReadAsArray(x, y, cols, rows)
                    prod5 = lpd_array
                    # TODO: Below is temporary until missing data values are
                    # fixed in LPD layer on GEE and missing data values are
                    # fixed in LPD layer made by UNCCD for SIDS
                    prod5[(prod5 == 0) | (prod5 == 15)] = -32768
                    # Mask areas outside of AOI
                    prod5[mask_array == -32767] = -32767

                # Recode prod5 as stable, degraded, improved (prod3)
                prod3 = prod5.copy()
                prod3[(prod5 >= 1) & (prod5 <= 3)] = -1
                prod3[prod5 == 4] = 0
                prod3[prod5 == 5] = 1

                ################
                # Calculate SDG
                deg_sdg = prod3.copy()

                lc_array = band_lc_deg.ReadAsArray(x, y, cols, rows)
                deg_sdg[lc_array == -1] = -1

                a_lc_bl = band_lc_bl.ReadAsArray(x, y, cols, rows)
                a_lc_bl[mask_array == -32767] = -32767
                a_lc_tg = band_lc_tg.ReadAsArray(x, y, cols, rows)
                a_lc_tg[mask_array == -32767] = -32767
                water = a_lc_tg == 7
                water = water.astype(bool, copy=False)

                # Note SOC array is coded in percent change, so change of
                # greater than 10% is improvement or decline.
                soc_array = band_soc_deg.ReadAsArray(x, y, cols, rows)
                deg_sdg[(soc_array <= -10) & (soc_array >= -100)] = -1

                # Allow improvements by lc or soc, only where one of the other
                # two indicators doesn't indicate a decline
                deg_sdg[(deg_sdg == 0) & (lc_array == 1)] = 1
                deg_sdg[(deg_sdg == 0) & (soc_array >= 10) & (soc_array <= 100)] = 1

                # Ensure all NAs are carried over - note this was already done
                # for the productivity layer above but need to do it again in
                # case values from another layer overwrote those missing value
                # indicators.

                # No data
                deg_sdg[(prod3 == -32768) | (lc_array == -32768) | (soc_array == -32768)] = -32768

                # Masked
                deg_sdg[mask_array == -32767] = -32767

                dst_ds_deg.GetRasterBand(1).WriteArray(deg_sdg, x, y)

                ###########################################################
                # Tabulate SDG 15.3.1 indicator
                # utils.log('deg_sdg.dtype: {}'.format(str(deg_sdg.dtype)))
                # utils.log('water.dtype: {}'.format(str(water.dtype)))
                # utils.log('cell_areas.dtype: {}'.format(str(cell_areas.dtype)))

                sdg_tbl_overall = sdg_tbl_overall + calculate.ldn_total_deg(
                    deg_sdg, water, cell_areas_array)
                sdg_tbl_prod = sdg_tbl_prod + calculate.ldn_total_deg(
                    prod3, water, cell_areas_array)
                sdg_tbl_lc = sdg_tbl_lc + calculate.ldn_total_deg(
                    lc_array,
                    np.array((mask_array == -32767) | water).astype(bool),
                    cell_areas_array
                )

                ###########################################################
                # Calculate SOC totals by transition, on annual basis
                a_trans_bl_tg = a_lc_bl * 10 + a_lc_tg
                a_trans_bl_tg[np.logical_or(a_lc_bl < 1, a_lc_tg < 1)] = -32768
                a_trans_bl_tg[mask_array == -32767] = -32767

                # Calculate SOC totals). Note final units of soc_totals tables
                # are tons C (summed over the total area of each class). Start
                # at one because the first soc band is the degradation layer.

                for i in range(1, len(self.soc_band_nums)):
                    band_soc = src_ds.GetRasterBand(self.soc_band_nums[i])
                    a_soc = band_soc.ReadAsArray(x, y, cols, rows)
                    # Convert soilgrids data from per ha to per meter since
                    # cell_area is in meters
                    a_soc = a_soc.astype(np.float32) / (100 * 100)  # From per ha to per m
                    a_soc[mask_array == -32767] = -32767

                    this_trans, this_totals = calculate.ldn_total_by_trans(
                        a_soc, a_trans_bl_tg, cell_areas_array)

                    new_trans, totals = ldn_total_by_trans_merge(
                        this_totals,
                        this_trans,
                        soc_totals_table[i - 1][1],
                        soc_totals_table[i - 1][0]
                    )
                    soc_totals_table[i - 1][0] = new_trans
                    soc_totals_table[i - 1][1] = totals

                    if i == 1:
                        # This is the baseline SOC - save it for later
                        a_soc_bl = a_soc.copy()
                    elif i == (len(self.soc_band_nums) - 1):
                        # This is the target (tg) SOC - save it for later
                        a_soc_tg = a_soc.copy()

                ###########################################################
                # Calculate transition crosstabs for productivity indicator
                this_rh, this_ch, this_xt = summary.xtab(
                    prod5, a_trans_bl_tg, cell_areas_array)
                # Don't use this transition xtab if it is empty (could
                # happen if take a xtab where all of the values are nan's)

                if this_rh.size != 0:
                    if xt is None:
                        rh = this_rh
                        ch = this_ch
                        xt = this_xt
                    else:
                        rh, ch, xt = summary.merge_xtabs(
                            this_rh, this_ch, this_xt, rh, ch, xt)

                a_soc_frac_chg = a_soc_tg / a_soc_bl
                # Degradation in terms of SOC is defined as a decline of more
                # than 10% (and improving increase greater than 10%)
                a_deg_soc = a_soc_frac_chg.astype(np.int16)
                a_deg_soc[(a_soc_frac_chg >= 0) & (a_soc_frac_chg <= .9)] = -1
                a_deg_soc[(a_soc_frac_chg > .9) & (a_soc_frac_chg < 1.1)] = 0
                a_deg_soc[a_soc_frac_chg >= 1.1] = 1
                # Mark areas that were no data in SOC
                a_deg_soc[a_soc_tg == -32768] = -32768  # No data
                # Carry over areas that were 1) originally masked, or 2) are
                # outside the AOI, or 3) are water
                sdg_tbl_soc = sdg_tbl_soc + calculate.ldn_total_deg(
                    a_deg_soc, water, cell_areas_array)

                # Start at one because remember the first lc band is the
                # degradation layer

                for i in range(1, len(self.lc_band_nums)):
                    band_lc = src_ds.GetRasterBand(self.lc_band_nums[i])
                    a_lc = band_lc.ReadAsArray(x, y, cols, rows)
                    a_lc[mask_array == -32767] = -32767
                    lc_totals_table[i - 1] = np.add(
                        [np.sum((a_lc == c) * cell_areas_array) for c in [1, 2, 3, 4, 5, 6, 7, -32768]],
                        lc_totals_table[i - 1])

                blocks += 1
            lat += pixel_height * rows
        self.progress.emit(100)

        # pr.disable()
        # pr.dump_stats('calculate_ldn_stats')

        if self.killed:
            del dst_ds_deg
            os.remove(self.prod_out_file)

            return None
        else:
            # Convert all area tables from meters into square kilometers

            return list((soc_totals_table,
                         lc_totals_table * 1e-6,
                         ((rh, ch), xt * 1e-6),
                         sdg_tbl_overall * 1e-6,
                         sdg_tbl_prod * 1e-6,
                         sdg_tbl_soc * 1e-6,
                         sdg_tbl_lc * 1e-6))


def _render_ldn_workbook(
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
        lc_legend_nesting: land_cover.LCLegendNesting,
        lc_trans_matrix: land_cover.LCTransitionDefinitionDeg,
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
            DegradationSummaryWorkerSDG,
            deg_worker_process_name,
            indic_vrt,
            prod_band_nums,
            prod_mode,
            str(output_sdg_path),
            lc_band_nums,
            soc_band_nums,
            mask_vrt,
            lc_legend_nesting,
            lc_trans_matrix
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
        lc_legend_nesting: land_cover.LCLegendNesting,
        lc_trans_matrix: land_cover.LCTransitionDefinitionDeg
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
        "lc_legend_nesting": lc_legend_nesting,
        "lc_trans_matrix": lc_trans_matrix,
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
        first.soc_totals[n] = summary.merge_area_tables(
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


def _write_overview_sdg_sheet(sheet, summary_table: SummaryTable):
    summary.write_table_to_sheet(
        sheet, np.transpose(summary_table.sdg_tbl_overall), 6, 6)
    utils.maybe_add_image_to_sheet("trends_earth_logo_bl_300width.png", sheet)


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
    utils.maybe_add_image_to_sheet("trends_earth_logo_bl_300width.png", sheet)


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
    utils.maybe_add_image_to_sheet("trends_earth_logo_bl_300width.png", sheet)


def _write_land_cover_sdg_sheet(sheet, summary_table: SummaryTable):
    summary.write_table_to_sheet(sheet, np.transpose(summary_table.sdg_tbl_lc), 6, 6)
    summary.write_table_to_sheet(
        sheet, _get_lc_table(summary_table.trans_prod_xtab), 26, 3)
    utils.maybe_add_image_to_sheet("trends_earth_logo_bl_300width.png", sheet)


def _write_unccd_reporting_sheet(
        sheet, summary_table: SummaryTable,
        land_cover_years,
        soil_organic_carbon_years):

    for i in range(len(land_cover_years)):
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
    utils.maybe_add_image_to_sheet("trends_earth_logo_bl_300width.png", sheet)


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


#TODO: Get this working in the jitted version in Numba
def ldn_total_by_trans_merge(total1, trans1, total2, trans2):
    """Calculates a total table for an array"""
    # Combine past totals with these totals
    trans = np.unique(np.concatenate((trans1, trans2)))
    totals = np.zeros(trans.size, dtype=np.float32)

    for i in range(trans.size):
        trans1_loc = np.where(trans1 == trans[i])[0]
        trans2_loc = np.where(trans2 == trans[i])[0]

        if trans1_loc.size > 0:
            totals[i] = totals[i] + total1[trans1_loc[0]]

        if trans2_loc.size > 0:
            totals[i] = totals[i] + total2[trans2_loc[0]]

    return trans, totals
