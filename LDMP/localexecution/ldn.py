import os
import dataclasses
import datetime as dt
import enum
import json
import tempfile
import re
import shutil

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

from ..conf import (
    settings_manager,
    Setting
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

if settings_manager.get_value(Setting.BINARIES_ENABLED):
    try:
        from trends_earth_binaries.ldn_numba import *
        log("Using numba-compiled version of ldn_numba.")
    except (ModuleNotFoundError, ImportError) as e:
        from .ldn_numba import *
        log(f"Failed import of numba-compiled code: {e}. "
            "Falling back to python version of ldn_numba.")
else:
    from .ldn_numba import *
    log("Using python version of ldn_numba.")

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
    lc_trans_zonal_areas: List[Dict[int, float]]
    lc_trans_prod_bizonal: Dict[Tuple[int, int], float]
    lc_trans_zonal_soc_initial: Dict[int, float]
    lc_trans_zonal_soc_final: Dict[int, float]
    sdg_summary: Dict[int, float]
    prod_summary: Dict[int, float]
    soc_summary: Dict[int, float]
    lc_summary: Dict[int, float]


def _accumulate_summary_tables(tables: List[SummaryTable]) -> SummaryTable:
    if len(tables) == 1:
        return tables[0]
    else:
        out = tables[0]
        for table in tables[1:]:
            out.soc_by_lc_annual_totals = [
                accumulate_dicts([a,  b])
                for a, b in zip(
                    out.soc_by_lc_annual_totals,
                    table.soc_by_lc_annual_totals
                )
            ]
            out.lc_annual_totals = [
                accumulate_dicts([a,  b])
                for a, b in zip(
                    out.lc_annual_totals,
                    table.lc_annual_totals
                )
            ]
            out.lc_trans_zonal_areas = [
                accumulate_dicts([a,  b])
                for a, b in zip(
                    out.lc_trans_zonal_areas,
                    table.lc_trans_zonal_areas
                )
            ]
            out.lc_trans_prod_bizonal = accumulate_dicts(
                [
                    out.lc_trans_prod_bizonal,
                    table.lc_trans_prod_bizonal
                ]
            )
            out.lc_trans_zonal_soc_initial = accumulate_dicts(
                [
                    out.lc_trans_zonal_soc_initial,
                    table.lc_trans_zonal_soc_initial
                ]
            )
            out.lc_trans_zonal_soc_final = accumulate_dicts(
                [
                    out.lc_trans_zonal_soc_final,
                    table.lc_trans_zonal_soc_final
                ]
            )
            out.sdg_summary = accumulate_dicts(
                [
                    out.sdg_summary,
                    table.sdg_summary
                ]
            )
            out.prod_summary = accumulate_dicts(
                [
                    out.prod_summary,
                    table.prod_summary
                ]
            )
            out.soc_summary = accumulate_dicts(
                [
                  out.soc_summary,
                    table.soc_summary
                ]
            )
            out.lc_summary = accumulate_dicts(
                [
                    out.lc_summary,
                    table.lc_summary
                ]
            )

        return out


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


@marshmallow_dataclass.dataclass
class DataFile(SchemaBase):
    path: str
    bands: List[models.JobBand]

    def array_rows_for_name(self, name_filter):
        names = [b.name for b in self.bands]

        return [
            index for index, name in enumerate(names)
            if name == name_filter
        ]

    def array_row_for_name(self, name_filter):
        '''throw an error if more than one result'''
        out = self.array_rows_for_name(name_filter)

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
    '''combine multiple datafiles with same path into one object'''

    return DataFile(
        path=path,
        bands=[
            b for d in datafiles for b in d.bands
        ]
    )


def compute_ldn(
        ldn_job: models.Job,
        area_of_interest: areaofinterest.AOI) -> models.Job:
    """Calculate final SDG 15.3.1 indicator and save its outputs to disk too."""

    job_output_path, _ = utils.get_local_job_output_paths(ldn_job)

    summary_tables = {}
    summary_table_stable_kwargs = {}

    period_dfs = []
    period_vrts = []

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
            summary_table, sdg_path, reproj_path = _compute_summary_table_from_te_prod(
                in_dfs=in_dfs,
                compute_bbs_from=traj.path,
                **summary_table_stable_kwargs[period]
            )
        elif prod_mode == LdnProductivityMode.JRC_LPD.value:
            lpd = _prepare_jrc_lpd_mode_vrt_path(period_params)
            in_dfs = lc_dfs + soc_dfs + [lpd]
            summary_table, sdg_path, reproj_path = _compute_summary_table_from_lpd_prod(
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
        sdg_df = DataFile(sdg_path, [sdg_band])

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
            sdg_df.bands.append(sdg_prod_band)

        reproj_df = _combine_data_files(reproj_path, in_dfs)
        # Don't add any of the input layers to the map by default - only SDG 
        # and prod, which are already marked add_to_map=True
        for band in reproj_df.bands:
            band.add_to_map = False

        period_vrt = job_output_path.parent / f"{sub_job_output_path.stem}_rasterdata.vrt"
        _combine_all_bands_into_vrt([reproj_path, sdg_path], period_vrt)

        # Now that there is a single VRT with all files in it, combine the DFs 
        # into it so that it can be used to source band names/metadata for the 
        # job bands list
        period_df = _combine_data_files(period_vrt, [sdg_df, reproj_df])
        for band in period_df.bands:
            band.metadata['period'] = period
        period_dfs.append(period_df)
        
        period_vrts.append(period_vrt)

        summary_table_output_path = sub_job_output_path.parent / f"{sub_job_output_path.stem}.xlsx"
        save_summary_table_excel(
            summary_table_output_path,
            summary_table,
            period_params["layer_lc_years"],
            period_params["layer_soc_years"],
            summary_table_stable_kwargs[period]['lc_legend_nesting'],
            summary_table_stable_kwargs[period]['lc_trans_matrix'],
            period
        )

    overall_vrt_path = job_output_path.parent / f"{job_output_path.stem}.vrt"
    _combine_all_bands_into_vrt(period_vrts, overall_vrt_path)
    out_df = _combine_data_files(overall_vrt_path, period_dfs)

    ldn_job.results.data_path = overall_vrt_path
    ldn_job.results.bands.extend(out_df.bands)

    # Also save bands to a key file for ease of use in PRAIS
    key_json = job_output_path.parent / f"{job_output_path.stem}_band_key.json"
    with open(key_json, 'w') as f:
        json.dump(DataFile.Schema().dump(out_df), f, indent=4)


    summary_json_output_path = job_output_path.parent / f"{job_output_path.stem}_summary.json"
    save_reporting_json(
        summary_json_output_path,
        summary_tables,
        ldn_job.params.params,
        ldn_job.params.task_name,
        area_of_interest,
        summary_table_stable_kwargs
    )
    ldn_job.end_date = dt.datetime.now(dt.timezone.utc)
    ldn_job.progress = 100

    return ldn_job


def _combine_all_bands_into_vrt(in_files: List[Path], out_file: Path):
    '''creates a vrt file combining all bands of in_files

    All bands must have the same extent, resolution, and crs
    '''

    simple_source_raw = '''    <SimpleSource>
        <SourceFilename relativeToVRT="1">{relative_path}</SourceFilename>
        <SourceBand>{source_band_num}</SourceBand>
        <SrcRect xOff="0" yOff="0" xSize="{out_Xsize}" ySize="{out_Ysize}"/>
        <DstRect xOff="0" yOff="0" xSize="{out_Xsize}" ySize="{out_Ysize}"/>
    </SimpleSource>'''
    
    for file_num, in_file in enumerate(in_files):
        in_ds = gdal.Open(str(in_file))
        this_gt = in_ds.GetGeoTransform()
        this_proj = in_ds.GetProjectionRef()
        if file_num == 0:
            out_gt = this_gt
            out_proj = this_proj
        else:
            assert out_gt == this_gt
            assert out_proj == this_proj

        for band_num in range(1, in_ds.RasterCount + 1):
            this_dt = in_ds.GetRasterBand(band_num).DataType
            this_band = in_ds.GetRasterBand(band_num)
            this_Xsize = this_band.XSize
            this_Ysize = this_band.YSize
            if band_num == 1:
                out_dt = this_dt
                out_Xsize = this_Xsize
                out_Ysize = this_Ysize
                if file_num == 0:
                    # If this is the first band of the first file, need to 
                    # create the output VRT file
                    driver = gdal.GetDriverByName("VRT")
                    out_ds = driver.Create(
                        str(out_file),
                        out_Xsize,
                        out_Ysize,
                        0,
                        out_dt
                    )
                    out_ds.SetGeoTransform(out_gt)
                    out_srs = osr.SpatialReference()
                    out_srs.ImportFromWkt(out_proj)
                    out_ds.SetProjection(out_srs.ExportToWkt())
            else:
                assert this_dt == out_dt
                assert this_Xsize == out_Xsize
                assert this_Ysize == out_Ysize

            out_ds.AddBand(out_dt)
            # The new band will always be last band in out_ds
            band = out_ds.GetRasterBand(out_ds.RasterCount)


            md = {}
            log(f'in_file.name: {in_file.name}')
            md['source_0'] = simple_source_raw.format(
                relative_path=in_file,
                source_band_num=band_num,
                out_Xsize=out_Xsize,
                out_Ysize=out_Ysize
            )
            band.SetMetadata(md, 'vrt_sources')

    out_ds = None

    # Use a regex to remove the parent elements from the paths for each band 
    # (have to include them when setting metadata or else GDAL throws an error)
    fh, new_file = tempfile.mkstemp()
    new_file = Path(new_file)
    with new_file.open('w') as fh_new:
        with out_file.open() as fh_old:
            for line in fh_old:
                fh_new.write(
                    line.replace(str(out_file.parents[0]), '.')
                )
    out_file.unlink()
    shutil.copy(str(new_file), str(out_file))

    return True


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


def _compute_summary_table_from_te_prod(
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


def _compute_summary_table_from_lpd_prod(
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


def save_summary_table_excel(
        output_path: Path,
        summary_table: SummaryTable,
        land_cover_years: List[int],
        soil_organic_carbon_years: List[int],
        lc_legend_nesting: land_cover.LCLegendNesting,
        lc_trans_matrix: land_cover.LCTransitionDefinitionDeg,
        period
):
    """Save summary table into an xlsx file on disk"""
    template_summary_table_path = Path(
        __file__).parents[1] / "data/summary_table_ldn_sdg.xlsx"
    workbook = openpyxl.load_workbook(str(template_summary_table_path))
    _render_ldn_workbook(
        workbook,
        summary_table,
        land_cover_years,
        soil_organic_carbon_years,
        lc_legend_nesting,
        lc_trans_matrix,
        period
    )
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

        n = 0
        crosstab_lcs = []
        for lc_trans_zonal_areas in st.lc_trans_zonal_areas:
            log(f'processing lc_trans_zonal_areas {i} for {period}')
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
            if n == 0:
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
            n += 1

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
                        final_value=st.lc_trans_zonal_soc_final.get(
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

def _process_block(
    params: DegradationSummaryWorkerParams,
    in_array,
    mask,
    xoff: int,
    yoff: int,
    cell_areas_raw
) -> Tuple[SummaryTable, Dict]:

    lc_bands = params.in_df.array_rows_for_name(LC_BAND_NAME)
    soc_bands = params.in_df.array_rows_for_name(SOC_BAND_NAME)
    soc_final_index = len(soc_bands) - 1
    if params.period == 'baseline':
        soc_band_counter_start = 0
    if params.period == 'progress':
        soc_band_counter_start = len(soc_bands) - 4
        soc_bands = soc_bands[-4:]

    # Create output array wit 2 bands
    #write_array = np.zeros((2, mask.shape[0], mask.shape[1]), dtype=np.int8)
    write_arrays = {}

    # Calculate cell area for each horizontal line
    # log('y: {}'.format(y))
    # log('x: {}'.format(x))
    # log('rows: {}'.format(rows))

    # Make an array of the same size as the input arrays containing
    # the area of each cell (which is identical for all cells in a
    # given row - cell areas only vary among rows)
    cell_areas = np.repeat(cell_areas_raw, mask.shape[1], axis=1).astype(np.float64)

    if params.prod_mode == 'Trends.Earth productivity':
        traj_array = in_array[params.in_df.array_row_for_name(TRAJ_BAND_NAME), :, :]
        traj_recode = recode_traj(traj_array)

        state_array = in_array[params.in_df.array_row_for_name(STATE_BAND_NAME), :, :]
        state_recode = recode_state(state_array)

        perf_array = in_array[params.in_df.array_row_for_name(PERF_BAND_NAME), :, :]

        deg_prod5 = calc_prod5(
            traj_recode,
            state_recode,
            perf_array
        )

        # Save combined productivity indicator for later visualization
        write_arrays[2] = {
            'array': deg_prod5,
            'xoff': xoff,
            'yoff': yoff
        }
    else:
        # TODO: Fix for accessing LPD
        lpd_array = in_array[params.in_df.array_row_for_name(LPD_BAND_NAME), :, :]
        deg_prod5 = lpd_array
        # TODO: Below is temporary until missing data values are
        # fixed in LPD layer on GEE and missing data values are
        # fixed in LPD layer made by UNCCD for SIDS
        deg_prod5[(deg_prod5 == 0) | (deg_prod5 == 15)] = NODATA_VALUE

    # Recode deg_prod5 as stable, degraded, improved (deg_prod3)
    deg_prod3 = prod5_to_prod3(deg_prod5)

    ###########################################################
    # Calculate SOC totals by transition, on annual basis
    a_trans_bl_tg_prod = calc_lc_trans(
        in_array[lc_bands[0], :, :],
        in_array[lc_bands[-1], :, :],
        params.trans_matrix.get_multiplier()
    )

    if params.period == 'baseline':
        # For baseline period crosstabs are over same period for all indicators
        a_trans_bl_tg_soc_lc = a_trans_bl_tg_prod
        lc_trans_arrays = [a_trans_bl_tg_soc_lc]
        lc_deg_bl = in_array[lc_bands[0], :, :]
        lc_deg_final = in_array[lc_bands[-1], :, :]

    if params.period == 'progress':
        # For progress period, need a transition matrix over just four years 
        # for SOC and LC
        a_trans_bl_tg_soc_lc = calc_lc_trans(
            in_array[lc_bands[-4], :, :],
            in_array[lc_bands[-1], :, :],
            params.trans_matrix.get_multiplier()
        )
        # For progress need a land cover crosstab of last four years in 
        # addition to full period crosstab
        lc_trans_arrays = [a_trans_bl_tg_prod, a_trans_bl_tg_soc_lc]
        lc_deg_bl = in_array[lc_bands[0], :, :]
        lc_deg_final = in_array[lc_bands[-4], :, :]

    # Calculate SOC totals by year. Note final units of soc_totals
    # tables are tons C (summed over the total area of each class).
    soc_by_lc_annual_totals = []
    for index, band_soc in enumerate(soc_bands, start=soc_band_counter_start):
        a_lc = in_array[lc_bands[index], :, :]
        a_soc = in_array[band_soc, :, :]
        soc_by_lc_annual_totals.append(
            zonal_total_weighted(
                a_lc,
                a_soc,
                cell_areas * 100,  # from sq km to hectares
                mask
            )
        )

        if index == soc_band_counter_start:
            # This is the baseline SOC - save it for later
            a_soc_bl = a_soc.copy()
        elif index == soc_final_index:
            # This is the target (tg) SOC - save it for later
            a_soc_final = a_soc.copy()

    lc_trans_zonal_soc_initial = zonal_total_weighted(
        a_trans_bl_tg_soc_lc,
        a_soc_bl,
        cell_areas * 100,  # from sq km to hectares
        mask
    )
    lc_trans_zonal_soc_final = zonal_total_weighted(
        a_trans_bl_tg_soc_lc,
        a_soc_final,
        cell_areas * 100,  # from sq km to hectares
        mask
    )

    ###########################################################
    # Calculate crosstabs for productivity
    lc_trans_prod_bizonal = bizonal_total(
        a_trans_bl_tg_prod,
        deg_prod5,
        cell_areas,
        mask
    )
    lc_annual_totals = []
    for band_lc in lc_bands:
        a_lc = in_array[band_lc, :, :]
        lc_annual_totals.append(
            zonal_total(
                a_lc,
                cell_areas,
                mask
            )
        )

    ###########################################################
    # Calculate crosstabs for land cover
    lc_trans_zonal_areas = []
    for a_trans in lc_trans_arrays:
        lc_trans_zonal_areas.append(
            zonal_total(
                a_trans,
                cell_areas,
                mask
            )
        )

    ################
    # Calculate SDG
    # Derive a water mask from last lc year
    water = in_array[lc_bands[-1], :, :] == 7
    water = water.astype(bool, copy=False)

    if params.period == 'baseline':
        deg_soc = in_array[params.in_df.array_row_for_name(SOC_DEG_BAND_NAME), :, :]
        deg_soc = recode_deg_soc(deg_soc, water)
        deg_lc = in_array[params.in_df.array_row_for_name(LC_DEG_BAND_NAME), :, :]
    if params.period == 'progress':
        deg_soc = calc_deg_soc(a_soc_bl, a_soc_final, water)
        lc_trans_matrix_list = params.trans_matrix.get_list()
        deg_lc = calc_deg_lc(
            lc_deg_bl,
            lc_deg_final,
            trans_code=lc_trans_matrix_list[0],
            trans_meaning=lc_trans_matrix_list[1],
            multiplier=params.trans_matrix.get_multiplier()
        )
    # write_arrays[3] = {
    #     'array': deg_lc,
    #     'xoff': xoff,
    #     'yoff': yoff
    # }


    deg_sdg = calc_deg_sdg(deg_prod3, deg_lc, deg_soc)
    write_arrays[1] = {
        'array': deg_sdg,
        'xoff': xoff,
        'yoff': yoff
    }

    ###########################################################
    # Tabulate SDG 15.3.1 indicator
    sdg_summary = zonal_total(
        deg_sdg,
        cell_areas,
        mask
    )
    prod_summary = zonal_total(
        deg_prod3,
        cell_areas,
        mask
    )
    lc_summary = zonal_total(
        deg_lc,
        cell_areas,
        mask
    )

    soc_summary = zonal_total(
        deg_soc,
        cell_areas,
        mask
    )

    return (
        SummaryTable(
            soc_by_lc_annual_totals,
            lc_annual_totals,
            lc_trans_zonal_areas,
            lc_trans_prod_bizonal,
            lc_trans_zonal_soc_initial,
            lc_trans_zonal_soc_final,
            sdg_summary,
            prod_summary,
            soc_summary,
            lc_summary
        ),
        write_arrays
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
        band_mask = mask_ds.GetRasterBand(1)

        src_ds = gdal.Open(str(self.params.in_df.path))

        if self.params.prod_mode == 'Trends.Earth productivity':
            traj_band = src_ds.GetRasterBand(
                self.params.in_df.array_row_for_name(TRAJ_BAND_NAME)
            )
            block_sizes = traj_band.GetBlockSize()
            xsize = traj_band.XSize
            ysize = traj_band.YSize
            # Save the combined productivity indicator as well, in the second
            # layer in the deg file
            n_out_bands = 2
        else:
            lpd_band = src_ds.GetRasterBand(
                self.params.in_df.array_row_for_name(LPD_BAND_NAME)
            )
            band_lc_deg = src_ds.GetRasterBand(
                self.params.in_df.array_row_for_name(LC_DEG_BAND_NAME)
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

        n_blocks = len(np.arange(0, xsize, x_block_size)) * len(np.arange(0, ysize, y_block_size))

        # pr = cProfile.Profile()
        # pr.enable()
        n = 0
        out = []
        for y in range(0, ysize, y_block_size):
            if y + y_block_size < ysize:
                win_ysize = y_block_size
            else:
                win_ysize = ysize - y

            cell_areas = np.array(
                [
                    calc_cell_area(
                        lat + pixel_height * n,
                        lat + pixel_height * (n + 1),
                        long_width
                    ) for n in range(win_ysize)
                ]
            ) * 1e-6  # 1e-6 is to convert from meters to kilometers
            cell_areas.shape = (cell_areas.size, 1)

            for x in range(0, xsize, x_block_size):
                if self.killed:
                    log("Processing killed by user after processing "
                        f"{n} out of {n_blocks} blocks.")
                    break
                self.progress.emit((n / n_blocks) * 100)
                
                if x + x_block_size < xsize:
                    win_xsize = x_block_size
                else:
                    win_xsize = xsize - x

                src_array = src_ds.ReadAsArray(
                    xoff=x,
                    yoff=y,
                    xsize=win_xsize,
                    ysize=win_ysize
                )

                mask_array = band_mask.ReadAsArray(
                    xoff=x,
                    yoff=y,
                    win_xsize=win_xsize,
                    win_ysize=win_ysize
                )
                mask_array = mask_array == MASK_VALUE

                result = _process_block(
                    self.params,
                    src_array,
                    mask_array,
                    x,
                    y,
                    cell_areas
                )

                out.append(result[0])

                for key, value in result[1].items():
                    dst_ds_deg.GetRasterBand(key).WriteArray(**value)

                n += 1
            if self.killed:
                break

            lat += pixel_height * win_ysize

        # pr.disable()
        # pr.dump_stats('calculate_ldn_stats')

        if self.killed:
            del dst_ds_deg
            os.remove(self.params.prod_out_file)
            return None
        else:
            self.progress.emit(100)
            return _accumulate_summary_tables(out)


def _render_ldn_workbook(
    template_workbook,
    summary_table: SummaryTable,
    lc_years: List[int],
    soc_years: List[int],
    lc_legend_nesting: land_cover.LCLegendNesting,
    lc_trans_matrix: land_cover.LCTransitionDefinitionDeg,
    period
):
    _write_overview_sheet(template_workbook["SDG 15.3.1"], summary_table)
    _write_productivity_sheet(
        template_workbook["Productivity"],
        summary_table,
        lc_trans_matrix
    )
    _write_soc_sheet(
        template_workbook["Soil organic carbon"],
        summary_table,
        lc_trans_matrix,
        period
    )
    _write_land_cover_sheet(
        template_workbook["Land cover"],
        summary_table,
        lc_trans_matrix,
        period
    )

    return template_workbook


def _calculate_summary_table(
        bbox,
        pixel_aligned_bbox,
        in_dfs: List[DataFile],
        output_sdg_path: Path,
        output_layers_path: Path,
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
    log(u'Reprojecting indicator VRT and saving to: {}'.format(output_layers_path))
    reproject_worker = worker.StartWorker(
        calculate.TranslateWorker,
        reproject_worker_process_name,
        str(output_layers_path),
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
            str(output_layers_path)
        )
        if mask_worker.success:
            in_df = _combine_data_files(output_layers_path, in_dfs)
            ######################################################################
            #  Calculate SDG 15.3.1 layers
            log(u'Calculating summary table and saving SDG to: {}'.format(output_sdg_path))
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
                if deg_worker.was_killed():
                    error_message = "Cancelled calculation of summary table."
                else:
                    error_message = "Error calculating SDG 15.3.1 summary table."
                result = None
            else:
                result = deg_worker.get_return()

        else:
            error_message = "Error creating mask."
            result = None

    else:
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
) -> Tuple[SummaryTable, Path, Path]:
    """Computes summary table and the output tif file(s)"""
    bbs = areaofinterest.get_aligned_output_bounds(
        compute_bbs_from,
        wkt_bounding_boxes
    )
    output_name_pattern = {
        1: f"{output_job_path.stem}" + "_{layer}.tif",
        2: f"{output_job_path.stem}" + "{layer}_{index}.tif"
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

    summary_tables = []
    reproj_paths = []
    sdg_paths = []
    for index, ( 
        wkt_bounding_box,
        pixel_aligned_bbox
    ) in enumerate(zip(wkt_bounding_boxes, bbs), start=1):
        sdg_path = output_job_path.parent / output_name_pattern.format(
            layer="sdg", index=index
        )
        sdg_paths.append(sdg_path)
        reproj_path = output_job_path.parent / output_name_pattern.format(
            layer="inputs", index=index
        )
        reproj_paths.append(reproj_path)
        result, error_message = _calculate_summary_table(
            bbox=wkt_bounding_box,
            pixel_aligned_bbox=pixel_aligned_bbox,
            output_sdg_path=sdg_path,
            output_layers_path=reproj_path,
            reproject_worker_process_name=reproject_name_fragment.format(index),
            mask_worker_process_name=mask_name_fragment.format(index),
            deg_worker_process_name=deg_name_fragment.format(index),
            **stable_kwargs
        )
        if result is None:
            raise RuntimeError(error_message)
        else:
            summary_tables.append(result)

    summary_table = _accumulate_summary_tables(summary_tables)

    if len(reproj_paths) > 1:
        reproj_path = output_job_path.parent / f"{output_job_path.stem}_inputs.vrt"
        gdal.BuildVRT(str(reproj_path), [str(p) for p in reproj_paths])
    else:
        reproj_path = reproj_paths[0]

    if len(sdg_paths) > 1:
        sdg_path = output_job_path.parent / f"{output_job_path.stem}_sdg.vrt"
        gdal.BuildVRT(str(sdg_path), [str(p) for p in sdg_paths])
    else:
        sdg_path = sdg_paths[0]

    return summary_table, sdg_path, reproj_path


def _get_summary_array(d):
    '''pulls summary values for excel sheet from a summary dictionary'''
    return np.array([
        d.get(1, 0.),
        d.get(0, 0.),
        d.get(-1, 0.),
        d.get(-32768, 0.)
    ])


def _write_overview_sheet(sheet, summary_table: SummaryTable):
    summary.write_col_to_sheet(
        sheet,
        _get_summary_array(summary_table.sdg_summary),
        6, 6
    )
    utils.maybe_add_image_to_sheet("trends_earth_logo_bl_300width.png", sheet)


def _write_productivity_sheet(
    sheet,
    st: SummaryTable,
    lc_trans_matrix: land_cover.LCTransitionDefinitionDeg
):
    summary.write_col_to_sheet(
        sheet, _get_summary_array(st.prod_summary),
        6, 6
    )
    summary.write_table_to_sheet(
        sheet,
        _get_prod_table(st.lc_trans_prod_bizonal, 5, lc_trans_matrix),
        16, 3
    )
    summary.write_table_to_sheet(
        sheet,
        _get_prod_table(st.lc_trans_prod_bizonal, 4, lc_trans_matrix),
        28, 3
    )
    summary.write_table_to_sheet(
        sheet,
        _get_prod_table(st.lc_trans_prod_bizonal, 3, lc_trans_matrix),
        40, 3
    )
    summary.write_table_to_sheet(
        sheet,
        _get_prod_table(st.lc_trans_prod_bizonal, 2, lc_trans_matrix),
        52, 3
    )
    summary.write_table_to_sheet(
        sheet,
        _get_prod_table(st.lc_trans_prod_bizonal, 1, lc_trans_matrix),
        64, 3
    )
    summary.write_table_to_sheet(
        sheet,
        _get_prod_table(st.lc_trans_prod_bizonal, NODATA_VALUE, lc_trans_matrix),
        76, 3
    )
    utils.maybe_add_image_to_sheet("trends_earth_logo_bl_300width.png", sheet)


def _write_soc_sheet(
    sheet,
    st: SummaryTable,
    lc_trans_matrix: land_cover.LCTransitionDefinitionDeg,
    period
):
    summary.write_col_to_sheet(
        sheet, _get_summary_array(st.soc_summary),
        6, 6
    )

    # First write baseline
    summary.write_col_to_sheet(
        sheet,
        _get_totals_by_lc_class_as_array(
            st.soc_by_lc_annual_totals[0],
            lc_trans_matrix,
            excluded_codes=[6]  # exclude water
        ),
        7, 16,
    )
    # Now write target
    summary.write_col_to_sheet(
        sheet,
        _get_totals_by_lc_class_as_array(
            st.soc_by_lc_annual_totals[-1],
            lc_trans_matrix,
            excluded_codes=[6]  # exclude water
        ),
        8, 16
    )
    if period == 'progress':
        # Progress period has shorter period for soc and lc
        baseline_index = -4
    else:
        baseline_index = 0
    # Write table of baseline areas
    lc_bl_no_water = _get_totals_by_lc_class_as_array(
        st.lc_annual_totals[baseline_index],
        lc_trans_matrix,
        excluded_codes=[6]  # exclude water
    )
    summary.write_col_to_sheet(
        sheet,
        lc_bl_no_water,
        5, 16
    )
    # Write table of final year areas
    lc_final_no_water = _get_totals_by_lc_class_as_array(
        st.lc_annual_totals[-1],
        lc_trans_matrix,
        excluded_codes=[6]  # exclude water
    )
    summary.write_col_to_sheet(
        sheet,
        lc_final_no_water,
        6, 16
    )

    # write_soc_stock_change_table has its own writing function as it needs to write a
    # mix of numbers and strings
    _write_soc_stock_change_table(
        sheet,
        27, 3,
        st.lc_trans_zonal_soc_initial,
        st.lc_trans_zonal_soc_final,
        lc_trans_matrix,
        excluded_codes=[6]  # exclude water
    )
    utils.maybe_add_image_to_sheet("trends_earth_logo_bl_300width.png", sheet)


def _write_land_cover_sheet(
    sheet,
    st: SummaryTable,
    lc_trans_matrix: land_cover.LCTransitionDefinitionDeg,
    period
):
    if period == 'progress':
        # Progress period has shorter period for soc and lc
        lc_trans_totals = st.lc_trans_zonal_areas[1]
    else:
        lc_trans_totals = st.lc_trans_zonal_areas[0]

    summary.write_col_to_sheet(
        sheet, _get_summary_array(st.lc_summary),
        6, 6
    )
    summary.write_table_to_sheet(
        sheet,
        _get_lc_trans_table(
            lc_trans_totals,
            lc_trans_matrix
        ),
        26, 3
    )
    utils.maybe_add_image_to_sheet("trends_earth_logo_bl_300width.png", sheet)


def _get_prod_table(lc_trans_prod_bizonal, prod_code, lc_trans_matrix):
    lc_codes = sorted([c.code for c in lc_trans_matrix.legend.key])
    out = np.zeros((len(lc_codes), len(lc_codes)))
    for i, i_code in enumerate(lc_codes):
        for f, f_code in enumerate(lc_codes):
            transition = i_code * lc_trans_matrix.get_multiplier() + f_code
            out[i, f] = lc_trans_prod_bizonal.get((transition, prod_code), 0.)
    return out


def _get_totals_by_lc_class_as_array(
    annual_totals,
    lc_trans_matrix,
    excluded_codes=[]  # to exclude water when used on SOC table
):
    lc_codes = sorted(
        [
            c.code for c in lc_trans_matrix.legend.key
            if c.code not in excluded_codes
        ]
    )
    return np.array([annual_totals.get(lc_code, 0.) for lc_code in lc_codes])


def _write_soc_stock_change_table(
    sheet,
    first_row,
    first_col,
    soc_bl_totals,
    soc_final_totals,
    lc_trans_matrix,
    excluded_codes=[]  # to exclude water
):
    lc_codes = sorted(
        [
            c.code for c in lc_trans_matrix.legend.key
            if c.code not in excluded_codes
        ]
    )
    for i, i_code in enumerate(lc_codes):
        for f, f_code in enumerate(lc_codes):
            cell = sheet.cell(row=i + first_row, column=f + first_col)
            transition = i_code * lc_trans_matrix.get_multiplier() + f_code
            bl_soc = soc_bl_totals.get(transition, 0.)
            final_soc = soc_final_totals.get(transition, 0.)
            try:
                cell.value = (final_soc - bl_soc) / bl_soc
            except ZeroDivisionError:
                cell.value = ''

def _get_lc_trans_table(
    lc_trans_totals,
    lc_trans_matrix,
    excluded_codes=[]
):
    lc_codes = sorted(
        [
            c.code for c in lc_trans_matrix.legend.key
            if c.code not in excluded_codes
        ]
    )
    out = np.zeros((len(lc_codes), len(lc_codes)))
    for i, i_code in enumerate(lc_codes):
        for f, f_code in enumerate(lc_codes):
            transition = i_code * lc_trans_matrix.get_multiplier() + f_code
            out[i, f] = lc_trans_totals.get(transition, 0.)
    return out


def _get_soc_total(soc_table, transition):
    ind = np.where(soc_table[0] == transition)[0]

    if ind.size == 0:
        return 0
    else:
        return float(soc_table[1][ind])
