import os
import dataclasses
import datetime as dt
import enum
import json
import tempfile
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed
)

from typing import (
    List,
    Dict,
    Tuple,
    Optional
)
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
    reporting,
    SchemaBase
)

from .ldn_numba import (
    calc_prod5,
    prod5_to_prod3,
    calc_deg_soc,
    recode_deg_soc,
    calc_deg_sdg,
    accumulate_dicts,
    zonal_total,
    bizonal_total,
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

import marshmallow_dataclass


NODATA_VALUE = -32768
MASK_VALUE = -32767

TRAJ_BAND_NAME = "Productivity trajectory (significance)"
PERF_BAND_NAME = "Productivity performance (degradation)"
STATE_BAND_NAME = "Productivity state (degradation)"
LPD_BAND_NAME = "SDG 15.3.1 Indicator (LPD)"
LC_DEG_BAND_NAME = "Land cover (degradation)"
LC_BAND_NAME = "Land cover (7 class)"
SOC_DEG_BAND_NAME = "Soil organic carbon (degradation)"
SOC_BAND_NAME = "Soil organic carbon"


class LdnProductivityMode(enum.Enum):
    TRENDS_EARTH = "Trends.Earth productivity"
    JRC_LPD = "JRC LPD"


@marshmallow_dataclass.dataclass
class SummaryTable(SchemaBase):
    soc_by_lc_annual_totals: List[Dict[int, float]]
    lc_annual_totals: List[Dict[int, float]]
    lc_trans_zonal_areas: Dict[int, float]
    lc_trans_prod_bizonal: List[Dict[Tuple[int, int], float]]
    lc_trans_zonal_soc_initial: Dict[int, float]
    lc_trans_zonal_soc_final: Dict[int, float]
    sdg_summary: Dict[int, float]
    prod_summary: Dict[int, float]
    soc_summary: Dict[int, float]
    lc_summary: Dict[int, float]


def _accumulate_summary_tables(
    first: SummaryTable,
    second: SummaryTable
) -> SummaryTable:

    first.soc_by_lc_annual_totals = [
        accumulate_dicts([a,  b])
        for a, b in zip(
            first.soc_by_lc_annual_totals,
            second.soc_by_lc_annual_totals
        )
    ]
    first.lc_annual_totals = [
        accumulate_dicts([a,  b])
        for a, b in zip(
            first.lc_annual_totals,
            second.lc_annual_totals
        )
    ]
    first.lc_trans_zonal_areas = [
        accumulate_dicts([a,  b])
        for a, b in zip(
            first.lc_trans_zonal_areas,
            second.lc_trans_zonal_areas
        )
    ]
    first.lc_trans_prod_bizonal = accumulate_dicts(
        [
            first.lc_trans_prod_bizonal,
            second.lc_trans_prod_bizonal
        ]
    )
    first.lc_trans_zonal_soc_initial = accumulate_dicts(
        [
            first.lc_trans_zonal_soc_initial,
            second.lc_trans_zonal_soc_initial
        ]
    )
    first.lc_trans_zonal_soc_final = accumulate_dicts(
        [
            first.lc_trans_zonal_soc_final,
            second.lc_trans_zonal_soc_final
        ]
    )
    first.sdg_summary = accumulate_dicts(
        [
            first.sdg_summary,
            second.sdg_summary
        ]
    )
    first.prod_summary = accumulate_dicts(
        [
            first.prod_summary,
            second.prod_summary
        ]
    )
    first.soc_summary = accumulate_dicts(
        [
          first.soc_summary,
            second.soc_summary
        ]
    )
    first.lc_summary = accumulate_dicts(
        [
            first.lc_summary,
            second.lc_summary
        ]
    )

    return first


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
    aux_bands: List[models.JobBand]
    aux_band_indexes: List[int]
    years: List[int]


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
    sorted_aux_bands = sorted(
        aux_bands,
        key=lambda i: i[0].metadata[sort_property]
    )
    aux_bands = [info[0] for info in sorted_aux_bands]
    aux_band_indexes = [info[1] for info in sorted_aux_bands]
    years = [i[0].metadata[sort_property] for i in sorted_aux_bands]

    return LdnInputInfo(
        path=usable_band_info.path,
        main_band=main_band,
        main_band_index=main_band_index,
        aux_bands=aux_bands,
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
        task_notes: Optional[str] = "",
) -> Dict:

    land_cover_inputs = _get_ldn_inputs(
        combo_layer_lc, "Land cover (7 class)")
    soil_organic_carbon_inputs = _get_ldn_inputs(
        combo_layer_soc, "Soil organic carbon")
    crosses_180th, geojsons = aoi.bounding_box_gee_geojson()

    traj_path = None
    traj_band = None
    traj_index = None
    traj_year_initial = None
    traj_year_final = None
    perf_path = None
    perf_band = None
    perf_index = None
    state_path = None
    state_band = None
    state_index = None
    lpd_path = None
    lpd_band = None
    lpd_index = None

    if prod_mode == LdnProductivityMode.TRENDS_EARTH.value:
        traj_band_info = combo_layer_traj.get_usable_band_info()
        traj_band = traj_band_info.band_info
        traj_path = str(traj_band_info.path)
        traj_index = traj_band_info.band_index
        traj_year_initial = traj_band_info.band_info.metadata['year_start']
        traj_year_final = traj_band_info.band_info.metadata['year_end']
        perf_band_info = combo_layer_perf.get_usable_band_info()
        perf_band = perf_band_info.band_info
        perf_path = str(perf_band_info.path)
        perf_index = perf_band_info.band_index
        state_band_info = combo_layer_state.get_usable_band_info()
        state_band = state_band_info.band_info
        state_path = str(state_band_info.path)
        state_index = state_band_info.band_index
    elif prod_mode == LdnProductivityMode.JRC_LPD.value:
        lpd_band_info = combo_layer_lpd.get_usable_band_info()
        lpd_band = lpd_band_info.band_info
        lpd_path = str(lpd_band_info.path)
        lpd_index = lpd_band_info.band_index

    return {
        "task_name": task_name,
        "task_notes": task_notes,
        "prod_mode": prod_mode,
        "layer_lc_path": str(land_cover_inputs.path),
        "layer_lc_main_band": models.JobBand.Schema().dump(
            land_cover_inputs.main_band
        ),
        "layer_lc_main_band_index": land_cover_inputs.main_band_index,
        "layer_lc_aux_bands": [
            models.JobBand.Schema().dump(b)
            for b in land_cover_inputs.aux_bands
        ],
        "layer_lc_aux_band_indexes": land_cover_inputs.aux_band_indexes,
        "layer_lc_years": land_cover_inputs.years,
        "layer_soc_path": str(soil_organic_carbon_inputs.path),
        "layer_soc_main_band": models.JobBand.Schema().dump(
            soil_organic_carbon_inputs.main_band
        ),
        "layer_soc_main_band_index": soil_organic_carbon_inputs.main_band_index,
        "layer_soc_aux_bands": [
            models.JobBand.Schema().dump(b)
            for b in soil_organic_carbon_inputs.aux_bands
        ],
        "layer_soc_aux_band_indexes": soil_organic_carbon_inputs.aux_band_indexes,
        "layer_soc_years": soil_organic_carbon_inputs.years,
        "layer_traj_path": traj_path,
        "layer_traj_band": models.JobBand.Schema().dump(traj_band),
        "layer_traj_band_index": traj_index,
        "layer_traj_year_initial": traj_year_initial,
        "layer_traj_year_final": traj_year_final,
        "layer_perf_band": models.JobBand.Schema().dump(perf_band),
        "layer_perf_path": perf_path,
        "layer_perf_band_index": perf_index,
        "layer_state_path": state_path,
        "layer_state_band": models.JobBand.Schema().dump(state_band),
        "layer_state_band_index": state_index,
        "layer_lpd_path": lpd_path,
        "layer_lpd_band": models.JobBand.Schema().dump(lpd_band),
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

    ldn_job.results.local_paths = []
    summary_tables = {}
    summary_table_stable_kwargs = {}

    for period, period_params in ldn_job.params.params.items():
        lc_dfs = _prepare_land_cover_file_paths(period_params)
        soc_dfs = _prepare_soil_organic_carbon_file_paths(period_params)
        sub_job_output_path = job_output_path.parent / f"{job_output_path.stem}_{period}.json"
        _, wkt_bounding_boxes = area_of_interest.meridian_split("layer", "wkt", warn=False)
        prod_mode = period_params["prod_mode"]

        period_params["layer_lc_main_band"]["metadata"]['nesting']

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
            "lc_legend_nesting": land_cover.LCLegendNesting.Schema().loads(
                period_params["layer_lc_main_band"]["metadata"]['nesting'],
            ),
            "lc_trans_matrix": land_cover.LCTransitionDefinitionDeg.Schema().loads(
                period_params["layer_lc_main_band"]["metadata"]['trans_matrix'],
            ),
            "soc_legend_nesting": land_cover.LCLegendNesting.Schema().loads(
                period_params["layer_soc_main_band"]["metadata"]['nesting'],
            ),
            "soc_trans_matrix": land_cover.LCTransitionDefinitionDeg.Schema().loads(
                period_params["layer_soc_main_band"]["metadata"]['trans_matrix'],
            ),
            "output_job_path": sub_job_output_path,
            "period": period,
        }

        if prod_mode == LdnProductivityMode.TRENDS_EARTH.value:
            traj, perf, state = _prepare_trends_earth_mode_vrt_paths(period_params)
            in_dfs = lc_dfs + soc_dfs + [traj, perf, state]
            summary_table, output_ldn_path, reproj_tifs = _compute_summary_table_from_te_productivity(
                in_dfs=in_dfs,
                compute_bbs_from=traj.path,
                **summary_table_stable_kwargs[period]
            )
        elif prod_mode == LdnProductivityMode.JRC_LPD.value:
            lpd = _prepare_jrc_lpd_mode_vrt_path(period_params)
            in_dfs = lc_dfs + soc_dfs + [lpd]
            summary_table, output_ldn_path, reproj_tifs = _compute_summary_table_from_lpd_productivity(
                in_dfs=in_dfs,
                compute_bbs_from=lpd.path,
                **summary_table_stable_kwargs[period],
            )
        else:
            raise RuntimeError(f"Invalid prod_mode: {prod_mode!r}")

        summary_tables[period] = summary_table

        sdg_band = models.JobBand(
            name="SDG 15.3.1 Indicator",
            no_data_value=NODATA_VALUE,
            metadata={
                'year_start': period_params['period']['year_start'],
                'year_final': period_params['period']['year_final'],
            },
            activated=True
        )
        ldn_job.results.bands.append(sdg_band)

        if prod_mode == LdnProductivityMode.TRENDS_EARTH.value:
            sdg_prod_band = models.JobBand(
                name="SDG 15.3.1 Productivity Indicator",
                no_data_value=NODATA_VALUE,
                metadata={
                    'year_start': period_params['prod_year_start'],
                    'year_final': period_params['prod_year_final'],
                },
                activated=True
            )
            ldn_job.results.bands.append(sdg_prod_band)

        reproj_tif_df = _combine_data_files(reproj_tifs, in_dfs)
        out_dfs = [
            DataFile(utils.save_vrt(reproj_tifs_df.path), job_band)
            for job_band in enumerate(reproj_tifs_df.bands)
        ].extend[
            DataFile(utils.save_vrt(output_ldn_path, 1), [sdg_band]),
            DataFile(utils.save_vrt(output_ldn_path, 1), [sdg_prod_band])
        ]

        out_vrt = tempfile.NamedTemporaryFile(suffix='.vrt').name
        gdal.BuildVRT(
            out_vrt,
            [item.path for item in out_dfs],
            resolution='highest',
            resampleAlg=gdal.GRA_NearestNeighbour,
            separate=True
        )
        out_combined_tif_path = job_output_path.parent / f"{job_output_path.stem}_{period}_layers.tif"
        gdal.Translate(
            str(out_combined_tif_path),
            out_vrt
        )

        out_combined_tif_path = job_output_path.parent / f"{job_output_path.stem}_{period}_layers_key.json"
        # Prep datafiles for writing to json
        out_dfs_str = []
        for df in out_dfs:
            out_dfs_str.append(models.JobBand.Schema().dump(df.bands[0]))
        with open(out_combined_tif_path, 'w') as f:
            json.dump(out_dfs_str, f, indent=4)

        # summary_table_output_path = sub_job_output_path.parent / f"{sub_job_output_path.stem}.xlsx"
        # save_summary_table(
        #     summary_table_output_path,
        #     summary_table,
        #     period_params["layer_lc_years"],
        #     period_params["layer_soc_years"],
        # )

        ldn_job.results.local_paths.extend([
            output_ldn_path,
            #summary_table_output_path
        ])

    summary_json_output_path = job_output_path.parent / f"{job_output_path.stem}_reporting.json"
    save_reporting_json(
        summary_json_output_path,
        summary_tables,
        ldn_job.params.params,
        ldn_job.params.task_name,
        area_of_interest,
        summary_table_stable_kwargs
    )
    ldn_job.results.local_paths.append(summary_json_output_path)
    ldn_job.end_date = dt.datetime.now(dt.timezone.utc)
    ldn_job.progress = 100

    return ldn_job


@dataclasses.dataclass()
class DataFile:
    path: str
    bands: List[models.JobBand]

    def band_nums_for_name(self, name_filter):
        names = [b.name for b in self.bands]

        return [
            index for index, name in enumerate(names, start=1)
            if name == name_filter
        ]

    def band_num_for_name(self, name_filter):
        '''just used so an error is thrown if more than one result'''
        names = [b.name for b in self.bands]

        out = [
            index for index, name in enumerate(names, start=1)
            if name == name_filter
        ]
        if len(out) > 1:
            raise RuntimeError(
                f'more than one band found for name {name_filter}'
            )
        else:
            return out[0]


def _combine_data_files(
    path,
    datafiles: List[models.JobBand]
) -> DataFile:

    return DataFile(
        path=path,
        bands=[
            b for d in datafiles for b in d.bands
        ]
    )


def _prepare_land_cover_file_paths(params: Dict) -> List[DataFile]:
    lc_path = params["layer_lc_path"]
    lc_dfs = [
        DataFile(
            path=utils.save_vrt(
                lc_path,
                params["layer_lc_main_band_index"]
            ),
            bands=[models.JobBand(**params["layer_lc_main_band"])]
        )
    ]
    for lc_aux_band, lc_aux_band_index, in zip(
        params["layer_lc_aux_bands"],
        params["layer_lc_aux_band_indexes"]
    ):
        lc_dfs.append(
            DataFile(
                path=utils.save_vrt(
                    lc_path,
                    lc_aux_band_index
                ),
                bands=[models.JobBand(**lc_aux_band)]
            )
        )

    return lc_dfs


def _prepare_soil_organic_carbon_file_paths(
    params: Dict
) -> List[DataFile]:
    soc_path = params["layer_soc_path"]
    soc_dfs = [
        DataFile(
            path=utils.save_vrt(
                soc_path,
                params["layer_soc_main_band_index"]
            ),
            bands=[models.JobBand(**params["layer_soc_main_band"])]
        )
    ]

    for soc_aux_band, soc_aux_band_index, in zip(
        params["layer_soc_aux_bands"],
        params["layer_soc_aux_band_indexes"]
    ):
        soc_dfs.append(
            DataFile(
                path=utils.save_vrt(
                    soc_path,
                    soc_aux_band_index
                ),
                bands=[models.JobBand(**soc_aux_band)]
            )
        )

    return soc_dfs


def _prepare_trends_earth_mode_vrt_paths(
    params: Dict
) -> Tuple[DataFile, DataFile, DataFile]:
    traj_vrt_df = DataFile(
        path=utils.save_vrt(
            params["layer_traj_path"],
            params["layer_traj_band_index"],
        ),
        bands=[models.JobBand(**params["layer_traj_band"])]
    )
    perf_vrt_df = DataFile(
        path=utils.save_vrt(
            params["layer_perf_path"],
            params["layer_perf_band_index"],
        ),
        bands=[models.JobBand(**params["layer_perf_band"])]
    )
    state_vrt_df = DataFile(
        path=utils.save_vrt(
            params["layer_state_path"],
            params["layer_state_band_index"],
        ),
        bands=[models.JobBand(**params["layer_state_band"])]
    )
    return traj_vrt_df, perf_vrt_df, state_vrt_df


def _prepare_jrc_lpd_mode_vrt_path(
    params: Dict
) -> DataFile:
    return DataFile(
        path=utils.save_vrt(
            params["layer_lpd_path"],
            params["layer_lpd_band_index"]
        ),
        bands=[models.JobBand(**params["layer_lpd_band"])]
    )


def _compute_summary_table_from_te_productivity(
        wkt_bounding_boxes,
        in_dfs,
        lc_legend_nesting: land_cover.LCLegendNesting,
        lc_trans_matrix: land_cover.LCTransitionDefinitionDeg,
        soc_legend_nesting: land_cover.LCLegendNesting,
        soc_trans_matrix: land_cover.LCTransitionDefinitionDeg,
        output_job_path: Path,
        period,
        compute_bbs_from
) -> Tuple[SummaryTable, Path]:
    '''Compute summary table if a trends.earth productivity dataset is used'''

    return _compute_ldn_summary_table(
        wkt_bounding_boxes=wkt_bounding_boxes,
        in_dfs=in_dfs,
        compute_bbs_from=compute_bbs_from,
        prod_mode=LdnProductivityMode.TRENDS_EARTH.value,
        output_job_path=output_job_path,
        lc_legend_nesting=lc_legend_nesting,
        lc_trans_matrix=lc_trans_matrix,
        period=period
    )


def _compute_summary_table_from_lpd_productivity(
        wkt_bounding_boxes,
        in_dfs,
        lc_legend_nesting: land_cover.LCLegendNesting,
        lc_trans_matrix: land_cover.LCTransitionDefinitionDeg,
        soc_legend_nesting: land_cover.LCLegendNesting,
        soc_trans_matrix: land_cover.LCTransitionDefinitionDeg,
        output_job_path: Path,
        period,
        compute_bbs_from
) -> Tuple[SummaryTable, Path]:
    '''Compute summary table if a JRC LPD productivity dataset is used'''

    return _compute_ldn_summary_table(
        wkt_bounding_boxes=wkt_bounding_boxes,
        in_dfs=in_dfs,
        compute_bbs_from=compute_bbs_from,
        prod_mode=LdnProductivityMode.JRC_LPD.value,
        output_job_path=output_job_path,
        lc_legend_nesting=lc_legend_nesting,
        lc_trans_matrix=lc_trans_matrix,
        period=period
    )


def save_summary_table(
        output_path: Path,
        summary_table: SummaryTable,
        land_cover_years: List[int],
        soil_organic_carbon_years: List[int]
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
        summary_tables: List[SummaryTable],
        params: dict,
        task_name: str,
        aoi: areaofinterest.AOI,
        summary_table_kwargs: dict):

    land_condition_reports = {}

    for period, period_params in params.items():
        st = summary_tables[period]

        ##########################################################################
        # Area summary tables
        lc_legend_nesting = summary_table_kwargs[period]['lc_legend_nesting']
        lc_trans_matrix = summary_table_kwargs[period]['lc_trans_matrix']

        sdg_summary = reporting.AreaList(
            'SDG Indicator 15.3.1',
            'sq km',
            [reporting.Area('Improved', st.sdg_summary.get(1, 0.)),
             reporting.Area('Stable', st.sdg_summary.get(0, 0.)),
             reporting.Area('Degraded', st.sdg_summary.get(-1, 0.)),
             reporting.Area('No data', st.sdg_summary.get(NODATA_VALUE, 0))]
        )

        prod_summary = reporting.AreaList(
            'Productivity',
            'sq km',
            [reporting.Area('Improved', st.prod_summary.get(1, 0.)),
             reporting.Area('Stable', st.prod_summary.get(0, 0.)),
             reporting.Area('Degraded', st.prod_summary.get(-1, 0.)),
             reporting.Area('No data', st.prod_summary.get(NODATA_VALUE, 0))]
        )

        soc_summary = reporting.AreaList(
            'Soil organic carbon',
            'sq km',
            [reporting.Area('Improved', st.soc_summary.get(1, 0.)),
             reporting.Area('Stable', st.soc_summary.get(0, 0.)),
             reporting.Area('Degraded', st.soc_summary.get(-1, 0.)),
             reporting.Area('No data', st.soc_summary.get(NODATA_VALUE, 0.))]
        )

        lc_summary = reporting.AreaList(
            'Land cover',
            'sq km',
            [reporting.Area('Improved', st.lc_summary.get(1, 0.)),
             reporting.Area('Stable', st.lc_summary.get(0, 0.)),
             reporting.Area('Degraded', st.lc_summary.get(-1, 0.)),
             reporting.Area('No data', st.lc_summary.get(NODATA_VALUE, 0.))]
        )

        #######################################################################
        # Productivity tables
        # TODO: Remove these hardcoded values
        classes = ['Tree-covered',
                   'Grassland',
                   'Cropland',
                   'Wetland',
                   'Artificial',
                   'Other land',
                   'Water body']
        crosstab_prod = []

        for prod_name, prod_code in zip(
            [
                'Increasing',
                'Stable',
                'Stressed',
                'Moderate decline',
                'Declining',
                'No data'
            ],
            [5, 4, 3, 2, 1, NODATA_VALUE]
        ):
            crosstab_entries = []

            for i, initial_class in enumerate(classes, start=1):
                for f, final_class in enumerate(classes, start=1):
                    transition = i * lc_trans_matrix.get_multiplier() + f
                    crosstab_entries.append(
                        reporting.CrossTabEntry(
                            initial_class,
                            final_class,
                            value=st.lc_trans_prod_bizonal.get(
                                (transition, prod_code),
                                0.
                            )
                        )
                    )
            crosstab_prod.append(
                reporting.CrossTab(
                    prod_name,
                    unit='sq km',
                    initial_year=period_params["prod_year_start"],
                    final_year=period_params["prod_year_final"],
                    values=crosstab_entries
                )
            )

        #######################################################################
        # Land cover tables
        land_cover_years = period_params["layer_lc_years"]

        i = 0
        crosstab_lcs = []
        for lc_trans_zonal_areas in st.lc_trans_zonal_areas:
            ###
            # LC transition cross tab
            lc_by_transition_type = []

            for i, initial_class in enumerate(classes, start=1):
                for f, final_class in enumerate(classes, start=1):
                    transition = i * lc_trans_matrix.get_multiplier() + f
                    lc_by_transition_type.append(
                        reporting.CrossTabEntry(
                            initial_class,
                            final_class,
                            value=lc_trans_zonal_areas.get(transition, 0.)
                        )
                    )
            lc_by_transition_type = sorted(
                lc_by_transition_type,
                key=lambda i: i.value,
                reverse=True
            )
            # TODO: VERY hackish, fix this after default data generation (years 
            # should be carried with the data)
            if i == 0:
                initial_lc_year = int(land_cover_years[0])
            else:
                initial_lc_year = int(land_cover_years[-4])
            crosstab_lc = reporting.CrossTab(
                name='Land area by land cover transition type',
                unit='sq km',
                initial_year=initial_lc_year,
                final_year=int(land_cover_years[-1]),
                # TODO: Check indexing as may be missing a class
                values=lc_by_transition_type
            )
            crosstab_lcs.append(crosstab_lc)
            i += 1

        ###
        # LC by year
        lc_by_year = {}

        for year_num, year in enumerate(land_cover_years):
            lc_by_year[int(year)] = {
                lc_class: st.lc_annual_totals[year_num].get(i, 0.)

                for i, lc_class in enumerate(classes, start=1)
            }
        lc_by_year_by_class = reporting.ValuesByYearDict(
            name='Area by year by land cover class',
            unit='sq km',
            values=lc_by_year
        )

        #######################################################################
        # Soil organic carbon tables
        soil_organic_carbon_years = period_params["layer_soc_years"]

        ###
        # SOC by transition type (initial and final stock for each transition
        # type)
        soc_by_transition = []
        # Note that the last element is skipped, as it is water, and don't want
        # to count water in SOC totals

        for i, initial_class in enumerate(classes[:-1], start=1):
            for f, final_class in enumerate(classes[:-1], start=1):
                transition = i * lc_trans_matrix.get_multiplier() + f
                soc_by_transition.append(
                    reporting.CrossTabEntryInitialFinal(
                        initial_label=initial_class,
                        final_label=final_class,
                        initial_value=st.lc_trans_zonal_soc_initial.get(
                            transition,
                            0.
                        ),
                        final_value=st.lc_trans_zonal_soc_initial.get(
                            transition,
                            0.
                        )
                    )
                )
        # TODO: VERY hackish, fix this after default data generation (years 
        # should be carried with the data)
        if period == 'baseline':
            initial_soc_year = int(soil_organic_carbon_years[0])
        else:
            initial_soc_year = int(soil_organic_carbon_years[-4])
        crosstab_soc_by_transition_per_ha = reporting.CrossTab(
            name='Initial and final carbon stock by transition type',
            unit='tons',
            initial_year=initial_soc_year,
            final_year=soil_organic_carbon_years[-1],
            values=soc_by_transition
        )

        ###
        # SOC by year by land cover class
        soc_by_year = {}

        # TODO: VERY hackish, fix this after default data generation (years 
        # should be carried with the data)
        if period == 'progress':
            soil_organic_carbon_years = soil_organic_carbon_years[-4:]
        for year_num, year in enumerate(soil_organic_carbon_years):
            soc_by_year[int(year)] = {
                lc_class: st.soc_by_lc_annual_totals[year_num].get(i, 0.)

                for i, lc_class in enumerate(classes[:-1], start=1)
            }
        soc_by_year_by_class = reporting.ValuesByYearDict(
            name='Soil organic carbon by year by land cover class',
            unit='tonnes',
            values=soc_by_year
        )


        ###
        # Setup this period's report
        land_condition_reports[period] = reporting.LandConditionReport(
            sdg=reporting.SDG15Report(summary=sdg_summary),

            productivity=reporting.ProductivityReport(
                summary=prod_summary,
                crosstabs_by_productivity_class=crosstab_prod
            ),

            land_cover=reporting.LandCoverReport(
                summary=lc_summary,
                legend_nesting=lc_legend_nesting,
                transition_matrix=lc_trans_matrix,
                crosstabs_by_land_cover_class=crosstab_lcs,
                land_cover_areas_by_year=lc_by_year_by_class
            ),

            soil_organic_carbon=reporting.SoilOrganicCarbonReport(
                summary=soc_summary,
                crosstab_by_land_cover_class=crosstab_soc_by_transition_per_ha,
                soc_stock_by_year=soc_by_year_by_class
            )
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
                    release_date=dt.datetime.strptime(
                        __release_date__,
                        '%Y/%m/%d %H:%M:%SZ'
                    )
                ),

                area_of_interest=schemas.AreaOfInterest(
                    name=task_name, # TODO replace this with area of interest name once implemented in TE
                    geojson=aoi.get_geojson(),
                    crs_wkt=aoi.get_crs_wkt()
                )
            ),

            land_condition=land_condition_reports,

            affected_population={},

            drought={}
        )

    try:
        te_summary_json = json.loads(
            reporting.TrendsEarthSummary.Schema().dumps(te_summary)
        )
        with open(output_path, 'w') as f:
            json.dump(te_summary_json, f, indent=4)

        return True

    except IOError:
        log(u'Error saving {}'.format(output_path))
        QtWidgets.QMessageBox.critical(
            None,
            tr("Error"),
            tr(
                "Error saving indicator table JSON - check that "
                f"{output_path} is accessible and not already open."
            )
        )

        return False


@dataclasses.dataclass()
class DegradationSummaryWorkerParams(SchemaBase):
    in_df: DataFile
    prod_mode: str
    prod_out_file: str
    mask_file: str
    nesting: land_cover.LCLegendNesting
    trans_matrix: land_cover.LCTransitionDefinitionDeg
    period: str

def _get_lc_trans(lc_bl, lc_tg, mask):
    a_trans_bl_tg = lc_bl * 10 + lc_tg
    a_trans_bl_tg[np.logical_or(lc_bl < 1, lc_tg < 1)] = NODATA_VALUE
    a_trans_bl_tg[mask] = MASK_VALUE
    return a_trans_bl_tg

def _process_block(
    params: DegradationSummaryWorkerParams,
    src_ds,
    mask_ds,
    dst_ds_deg,
    y: int,
    rows: int,
    xsize: int,
    ysize: int,
    x_block_size: int,
    y_block_size: int,
    cell_areas_raw
):

    lc_bands = params.in_df.band_nums_for_name(LC_BAND_NAME)
    lc_annual_totals = [[] for i in range(len(lc_bands))]
    soc_bands = params.in_df.band_nums_for_name(SOC_BAND_NAME)
    soc_tg_index = len(soc_bands) - 1
    if params.period == 'baseline':
        lc_trans_zonal_areas = [[]]
        soc_band_counter_start = 0
    if params.period == 'progress':
        lc_trans_zonal_areas = [[], []]
        soc_band_counter_start = len(soc_bands) - 4
        soc_bands = soc_bands[-4:]
    soc_by_lc_annual_totals = [[] for i in range(len(soc_bands))]
    lc_trans_prod_bizonal = []
    lc_trans_zonal_soc_initial = []
    lc_trans_zonal_soc_final = []
    sdg_summary = []
    prod_summary = []
    soc_summary = []
    lc_summary = []

    for x in range(0, xsize, x_block_size):
        if x + x_block_size < xsize:
            cols = x_block_size
        else:
            cols = xsize - x

        band_mask = mask_ds.GetRasterBand(1)
        mask = band_mask.ReadAsArray(x, y, cols, rows)
        mask = mask == MASK_VALUE

        # Calculate cell area for each horizontal line
        # log('y: {}'.format(y))
        # log('x: {}'.format(x))
        # log('rows: {}'.format(rows))

        # Make an array of the same size as the input arrays containing
        # the area of each cell (which is identical for all cells in a
        # given row - cell areas only vary among rows)
        cell_areas = np.repeat(cell_areas_raw, cols, axis=1).astype(np.float32)

        if params.prod_mode == 'Trends.Earth productivity':
            traj_band = src_ds.GetRasterBand(
                params.in_df.band_num_for_name(TRAJ_BAND_NAME)
            )
            traj_recode = calculate.ldn_recode_traj(
                traj_band.ReadAsArray(x, y, cols, rows)
            )

            state_band = src_ds.GetRasterBand(
                params.in_df.band_num_for_name(STATE_BAND_NAME)
            )
            state_recode = calculate.ldn_recode_state(
                state_band.ReadAsArray(x, y, cols, rows)
            )

            perf_band = src_ds.GetRasterBand(
                params.in_df.band_num_for_name(PERF_BAND_NAME)
            )
            perf_array = perf_band.ReadAsArray(x, y, cols, rows)
            deg_prod5 = calc_prod5(
                traj_recode,
                state_recode,
                perf_array,
                mask
            )

            # Save combined productivity indicator for later visualization
            dst_ds_deg.GetRasterBand(2).WriteArray(deg_prod5, x, y)
        else:
            lpd_band = src_ds.GetRasterBand(
                params.in_df.band_num_for_name(LPD_BAND_NAME)
            )
            lpd_array = lpd_band.ReadAsArray(x, y, cols, rows)
            deg_prod5 = lpd_array
            # TODO: Below is temporary until missing data values are
            # fixed in LPD layer on GEE and missing data values are
            # fixed in LPD layer made by UNCCD for SIDS
            deg_prod5[(deg_prod5 == 0) | (deg_prod5 == 15)] = NODATA_VALUE
            # Mask areas outside of AOI
            deg_prod5[mask] = MASK_VALUE

        # Recode deg_prod5 as stable, degraded, improved (deg_prod3)
        deg_prod3 = prod5_to_prod3(deg_prod5)

        ###########################################################
        # Calculate SOC totals by transition, on annual basis
        if params.period == 'baseline':
            a_lc_bl = src_ds.GetRasterBand(
                lc_bands[0]
            ).ReadAsArray(x, y, cols, rows)
            a_lc_bl[mask] = MASK_VALUE
            a_lc_tg = src_ds.GetRasterBand(
                lc_bands[-1]
            ).ReadAsArray(x, y, cols, rows)
            a_lc_tg[mask] = MASK_VALUE
            a_trans_bl_tg = _get_lc_trans(a_lc_bl, a_lc_tg, mask)
            a_trans_bl_tg_prod = a_trans_bl_tg
            # For baseline don't need a land cover crosstab of last four years
            lc_trans_arrays = [a_trans_bl_tg]

        if params.period == 'progress':
            a_lc_bl = src_ds.GetRasterBand(
                lc_bands[-4]
            ).ReadAsArray(x, y, cols, rows)
            a_lc_bl[mask] = MASK_VALUE
            band_lc_tg = src_ds.GetRasterBand(lc_bands[-1])
            a_lc_tg = band_lc_tg.ReadAsArray(x, y, cols, rows)
            a_lc_tg[mask] = MASK_VALUE
            a_trans_bl_tg = _get_lc_trans(a_lc_bl, a_lc_tg, mask)

            # For progress period, need a transition matrix over just four 
            # years
            a_lc_bl_prod = src_ds.GetRasterBand(
                lc_bands[-1]
            ).ReadAsArray(x, y, cols, rows)
            a_lc_bl_prod[mask] = MASK_VALUE
            a_trans_bl_tg_prod = _get_lc_trans(a_lc_bl_prod, a_lc_tg, mask)
            # For progress need a land cover crosstab of last four years
            lc_trans_arrays = [a_trans_bl_tg_prod, a_trans_bl_tg]

        # Calculate SOC totals by year. Note final units of soc_totals
        # tables are tons C (summed over the total area of each class).
        for index, band_soc in enumerate(soc_bands, start=soc_band_counter_start):
            band_soc = src_ds.GetRasterBand(band_soc)
            band_lc = src_ds.GetRasterBand(lc_bands[index])
            a_lc = band_lc.ReadAsArray(x, y, cols, rows)
            a_soc = band_soc.ReadAsArray(x, y, cols, rows)
            # Convert soilgrids data from per ha to per sq kilometer
            a_soc = a_soc.astype(np.float32) * 100
            soc_by_lc_annual_totals[index - soc_band_counter_start].append(
                zonal_total(
                    a_lc,
                    a_soc*cell_areas,
                    mask
                )
            )

            if index == soc_band_counter_start:
                # This is the baseline SOC - save it for later
                a_soc_bl = a_soc.copy()
            elif index == soc_tg_index:
                # This is the target (tg) SOC - save it for later
                a_soc_tg = a_soc.copy()

        lc_trans_zonal_soc_initial.append(
            zonal_total(
                a_trans_bl_tg,
                a_soc_bl * cell_areas,
                mask
            )
        )
        lc_trans_zonal_soc_final.append(
            zonal_total(
                a_trans_bl_tg,
                a_soc_tg * cell_areas,
                mask
            )
        )

        ###########################################################
        # Calculate crosstabs for productivity
        lc_trans_prod_bizonal.append(
            bizonal_total(
                a_trans_bl_tg_prod,
                deg_prod5,
                cell_areas,
                mask
            )
        )
        for index, band_lc in enumerate(lc_bands):
            band_lc = src_ds.GetRasterBand(band_lc)
            a_lc = band_lc.ReadAsArray(x, y, cols, rows)
            lc_annual_totals[index].append(
                zonal_total(
                    a_lc,
                    cell_areas,
                    mask
                )
            )

        ###########################################################
        # Calculate crosstabs for land cover
        for index, a_trans in enumerate(lc_trans_arrays):
            lc_trans_zonal_areas[index].append(
                zonal_total(
                    a_trans,
                    cell_areas,
                    mask
                )
            )

        ################
        # Calculate SDG
        band_lc_deg = src_ds.GetRasterBand(
            params.in_df.band_num_for_name(LC_DEG_BAND_NAME)
        )
        deg_lc = band_lc_deg.ReadAsArray(x, y, cols, rows)
        water = a_lc_tg == 7
        water = water.astype(bool, copy=False)

        band_soc_deg = src_ds.GetRasterBand(
            params.in_df.band_num_for_name(SOC_DEG_BAND_NAME)
        )
        soc_array = band_soc_deg.ReadAsArray(x, y, cols, rows)
        if params.period == 'baseline':
            deg_soc = recode_deg_soc(soc_array, water, mask)
        if params.period == 'progress':
            deg_soc = calc_deg_soc(a_soc_bl, a_soc_tg, water, mask)

        deg_sdg = calc_deg_sdg(deg_prod3, deg_lc, deg_soc, mask)
        dst_ds_deg.GetRasterBand(1).WriteArray(deg_sdg, x, y)

        ###########################################################
        # Tabulate SDG 15.3.1 indicator
        # utils.log('deg_sdg.dtype: {}'.format(str(deg_sdg.dtype)))
        # utils.log('water.dtype: {}'.format(str(water.dtype)))
        # utils.log('cell_areas.dtype: {}'.format(str(cell_areas.dtype)))
        sdg_summary.append(
            zonal_total(
                deg_sdg,
                cell_areas,
                mask
            )
        )
        prod_summary.append(
            zonal_total(
                deg_prod3,
                cell_areas,
                mask
            )
        )
        lc_summary.append(
            zonal_total(
                deg_lc,
                cell_areas,
                mask
            )
        )

        soc_summary.append(
            zonal_total(
                deg_soc,
                cell_areas,
                mask
            )
        )


    return SummaryTable(
        [accumulate_dicts(item) for item in soc_by_lc_annual_totals],
        [accumulate_dicts(item) for item in lc_annual_totals],
        [accumulate_dicts(item) for item in lc_trans_zonal_areas],
        accumulate_dicts(lc_trans_prod_bizonal),
        accumulate_dicts(lc_trans_zonal_soc_initial),
        accumulate_dicts(lc_trans_zonal_soc_final),
        accumulate_dicts(sdg_summary),
        accumulate_dicts(prod_summary),
        accumulate_dicts(soc_summary),
        accumulate_dicts(lc_summary)
    )


class DegradationSummaryWorker(worker.AbstractWorker):
    def __init__(
        self,
        params: DegradationSummaryWorkerParams
    ):

        worker.AbstractWorker.__init__(self)

        self.params = params

    def work(self):
        self.toggle_show_progress.emit(True)
        self.toggle_show_cancel.emit(True)

        mask_ds = gdal.Open(self.params.mask_file)

        src_ds = gdal.Open(self.params.in_df.path)

        if self.params.prod_mode == 'Trends.Earth productivity':
            traj_band = src_ds.GetRasterBand(
                self.params.in_df.band_num_for_name(TRAJ_BAND_NAME)
            )
            block_sizes = traj_band.GetBlockSize()
            xsize = traj_band.XSize
            ysize = traj_band.YSize
            # Save the combined productivity indicator as well, in the second
            # layer in the deg file
            n_out_bands = 2
        else:
            lpd_band = src_ds.GetRasterBand(
                self.params.in_df.band_num_for_name(LPD_BAND_NAME)
            )
            band_lc_deg = src_ds.GetRasterBand(
                self.params.in_df.band_num_for_name(LC_DEG_BAND_NAME)
            )
            block_sizes = band_lc_deg.GetBlockSize()
            xsize = band_lc_deg.XSize
            ysize = band_lc_deg.YSize
            n_out_bands = 1

        x_block_size = block_sizes[0]
        y_block_size = block_sizes[1]

        # Setup output file for SDG degradation indicator and combined
        # productivity bands
        driver = gdal.GetDriverByName("GTiff")
        dst_ds_deg = driver.Create(
            self.params.prod_out_file,
            xsize,
            ysize,
            n_out_bands,
            gdal.GDT_Int16, options=['COMPRESS=LZW']
        )
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

        xt = None
        # Minus 1 as first band is degradation, not an annual layer

        # pr = cProfile.Profile()
        # pr.enable()
        with ThreadPoolExecutor(max_workers=4) as executor:
            res = []

            for y in range(0, ysize, y_block_size):
                if self.killed:
                    log("Processing killed by user after processing "
                        f"{y} out of {y_size} blocks.")

                    break

                if y + y_block_size < ysize:
                    rows = y_block_size
                else:
                    rows = ysize - y

                cell_areas = np.array(
                    [
                        summary.calc_cell_area(
                            lat + pixel_height * n,
                            lat + pixel_height * (n + 1),
                            long_width
                        ) for n in range(rows)
                    ]
                ) * 1e-6  # 1e-6 is to convert from meters to kilometers
                cell_areas.shape = (cell_areas.size, 1)

                res.append(
                    executor.submit(
                        _process_block,
                        self.params,
                        src_ds,
                        mask_ds,
                        dst_ds_deg,
                        y,
                        rows,
                        xsize,
                        ysize,
                        x_block_size,
                        y_block_size,
                        cell_areas
                    )
                )

                lat += pixel_height * rows

            out = None
            res_counter = 0
            for this_res in as_completed(res):
                self.progress.emit((res_counter / len(res)) * 100)

                if out is None:
                    out = this_res.result()
                else:
                    out = _accumulate_summary_tables(
                        out,
                        this_res.result()
                    )
                res_counter += 1

            self.progress.emit(100)

        # pr.disable()
        # pr.dump_stats('calculate_ldn_stats')

        if self.killed:
            del dst_ds_deg
            os.remove(self.prod_out_file)

            return None
        else:
            return out

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
        in_dfs: List[DataFile],
        output_sdg_path: Path,
        prod_mode: str,
        lc_legend_nesting: land_cover.LCLegendNesting,
        lc_trans_matrix: land_cover.LCTransitionDefinitionDeg,
        reproject_worker_process_name,
        mask_worker_process_name,
        deg_worker_process_name,
        period
) -> Tuple[
    Optional[SummaryTable],
    str
]:
    # build vrt
    # Combines SDG 15.3.1 input raster into a VRT and crop to the AOI
    indic_vrt = tempfile.NamedTemporaryFile(suffix='.vrt').name
    log(u'Saving indicator VRT to: {}'.format(indic_vrt))
    # The plus one is because band numbers start at 1, not zero
    gdal.BuildVRT(
        indic_vrt,
        [item.path for item in in_dfs],
        outputBounds=pixel_aligned_bbox,
        resolution='highest',
        resampleAlg=gdal.GRA_NearestNeighbour,
        separate=True
    )
    reproj_tif = tempfile.NamedTemporaryFile(suffix='.tif').name
    log(u'Reprojecting indicator VRT and saving to: {}'.format(reproj_tif))
    reproject_worker = worker.StartWorker(
        calculate.TranslateWorker,
        reproject_worker_process_name,
        reproj_tif,
        indic_vrt
    )
    error_message = ""

    if reproject_worker.success:
        # Compute a mask layer that will be used in the tabulation code to
        # mask out areas outside of the AOI. Do this instead of using
        # gdal.Clip to save having to clip and rewrite all of the layers in
        # the VRT
        mask_vrt = tempfile.NamedTemporaryFile(suffix='.tif').name
        log(u'Saving mask to {}'.format(mask_vrt))
        geojson = calculate.json_geom_to_geojson(
            qgis.core.QgsGeometry.fromWkt(bbox).asJson())
        mask_worker = worker.StartWorker(
            calculate.MaskWorker,
            mask_worker_process_name,
            mask_vrt,
            geojson,
            reproj_tif
        )
        if mask_worker.success:
            in_df = _combine_data_files(reproj_tif, in_dfs)
            ######################################################################
            #  Calculate SDG 15.3.1 layers
            log('Calculating summary table...')
            deg_worker = worker.StartWorker(
                DegradationSummaryWorker,
                deg_worker_process_name,
                DegradationSummaryWorkerParams(
                    in_df=in_df,
                    prod_mode=prod_mode,
                    prod_out_file=str(output_sdg_path),
                    mask_file=mask_vrt,
                    nesting=lc_legend_nesting,
                    trans_matrix=lc_trans_matrix,
                    period=period
                )
            )

            if not deg_worker.success:
                error_message = "Error calculating SDG 15.3.1 summary table."
                result = None

            else:
                result = (reproj_tig, deg_worker.get_return())

        else:
            error_message = "Error creating mask."
            result = None

        error_message = "Error reprojecting layers."
        result = None

    return result, error_message


def _compute_ldn_summary_table(
    wkt_bounding_boxes,
    in_dfs,
    compute_bbs_from,
    prod_mode,
    output_job_path: Path,
    lc_legend_nesting: land_cover.LCLegendNesting,
    lc_trans_matrix: land_cover.LCTransitionDefinitionDeg,
    period
) -> Tuple[SummaryTable, Path]:
    """Computes summary table and the output tif file(s)"""
    bbs = areaofinterest.get_aligned_output_bounds(
        compute_bbs_from,
        wkt_bounding_boxes
    )
    output_name_pattern = {
        1: f"{output_job_path.stem}.tif",
        2: f"{output_job_path.stem}" + "_{index}.tif"
    }[len(wkt_bounding_boxes)]
    reproject_name_fragment = {
        1: "Reprojecting layers",
        2: "Reprojecting layers (part {index} of 2)",
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
        "in_dfs": in_dfs,
        "prod_mode": prod_mode,
        "lc_legend_nesting": lc_legend_nesting,
        "lc_trans_matrix": lc_trans_matrix,
        "period": period,
    }
    output_path = output_job_path.parent / output_name_pattern.format(index=1)
    result, error_message = _calculate_summary_table(
        bbox=wkt_bounding_boxes[0],
        pixel_aligned_bbox=bbs[0],
        output_sdg_path=output_path,
        reproject_worker_process_name=reproject_name_fragment.format(index=1),
        mask_worker_process_name=mask_name_fragment.format(index=1),
        deg_worker_process_name=deg_name_fragment.format(index=1),
        **stable_kwargs
    )
    reproj_tifs = [result[0]]
    summary_table = result[1]

    if summary_table is None:
        raise RuntimeError(error_message)

    if len(wkt_bounding_boxes) > 1:
        tile_output_path = output_job_path.parent / output_name_pattern.format(index=2)
        result_2, error_message = _calculate_summary_table(
            bbox=wkt_bounding_boxes[1],
            pixel_aligned_bbox=bbs[1],
            output_sdg_path=tile_output_path,
            reproject_worker_process_name=reproject_name_fragment.format(index=2),
            mask_worker_process_name=mask_name_fragment.format(index=2),
            deg_worker_process_name=deg_name_fragment.format(index=2),
            **stable_kwargs
        )
        reproj_tif_2 = result[0]
        summary_table_2 = result_2[1]

        if summary_table_2 is None:
            raise RuntimeError(error_message)
        summary_table = _accumulate_summary_tables(
            summary_table, summary_table_2)
        output_path = output_job_path.parent / f"{output_job_path.stem}.vrt"

        reproj_tifs.append = [reproj_tif_2]

    return summary_table, output_path, reproj_tifs


def _write_overview_sdg_sheet(sheet, summary_table: SummaryTable):
    summary.write_table_to_sheet(
        sheet, np.transpose(summary_table.sdg_summary), 6, 6)
    utils.maybe_add_image_to_sheet("trends_earth_logo_bl_300width.png", sheet)


def _write_productivity_sdg_sheet(sheet, summary_table: SummaryTable):
    summary.write_table_to_sheet(
        sheet, np.transpose(summary_table.prod_summary), 6, 6)
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
        sheet, _get_prod_table(summary_table.trans_prod_xtab, NODATA_VALUE), 76, 3)
    utils.maybe_add_image_to_sheet("trends_earth_logo_bl_300width.png", sheet)


def _write_soc_sdg_sheet(sheet, summary_table: SummaryTable):
    summary.write_table_to_sheet(sheet, np.transpose(summary_table.soc_summary), 6, 6)
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
    summary.write_table_to_sheet(sheet, np.transpose(summary_table.lc_summary), 6, 6)
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
        lpd_classes=[1, 2, 3, 4, 5, NODATA_VALUE]
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
