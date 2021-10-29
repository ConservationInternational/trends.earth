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
        from trends_earth_binaries.util_numba import *
        log("Using numba-compiled version of util_numba.")
        from trends_earth_binaries.drought_numba import *
        log("Using numba-compiled version of ldn_numba.")
    except (ModuleNotFoundError, ImportError) as e:
        from .util_numba import *
        log(f"Failed import of numba-compiled code: {e}. "
            "Falling back to python version of util_numba.")
        from .drought_numba import *
        log(f"Failed import of numba-compiled code: {e}. "
            "Falling back to python version of drought_numba.")
else:
    from .ldn_numba import *
    log("Using python version of ldn_numba.")

import marshmallow_dataclass


NODATA_VALUE = -32768
MASK_VALUE = -32767

POPULATION_BAND_NAME = "Population (density, persons per sq km / 10)"
SPI_BAND_NAME = "Standardized Precipitation Index (SPI)"
JRC_BAND_NAME = "Drought Vulnerability (JRC)"


@marshmallow_dataclass.dataclass
class SummaryTableDrought(SchemaBase):
    annual_area_by_drought_class: List[Dict[int, float]]
    annual_population_by_drought_class_total: List[Dict[int, float]]
    annual_population_by_drought_class_male: List[Dict[int, float]]
    annual_population_by_drought_class_female: List[Dict[int, float]]
    dvi_value_sum_and_count: Tuple[float, int]

def _accumulate_summary_tables(
    tables: List[SummaryTableDrought]
) -> SummaryTableDrought:
    if len(tables) == 1:
        return tables[0]
    else:
        out = tables[0]
        for table in tables[1:]:
            out.annual_area_by_drought_class = [
                accumulate_dicts([a,  b])
                for a, b in zip(
                    out.annual_area_by_drought_class,
                    table.annual_area_by_drought_class
                )
            ]
            out.annual_population_by_drought_class_total = [
                accumulate_dicts([a,  b])
                for a, b in zip(
                    out.annual_population_by_drought_class_total,
                    table.annual_population_by_drought_class_total
                )
            ]
            out.annual_population_by_drought_class_male = [
                accumulate_dicts([a,  b])
                for a, b in zip(
                    out.annual_population_by_drought_class_male,
                    table.annual_population_by_drought_class_male
                )
            ]
            out.annual_population_by_drought_class_female = [
                accumulate_dicts([a,  b])
                for a, b in zip(
                    out.annual_population_by_drought_class_female,
                    table.annual_population_by_drought_class_female
                )
            ]
            out.dvi_value_sum_and_count = (
                out.dvi_value_sum_and_count[0] +
                table.dvi_value_sum_and_count[0],
                out.dvi_value_sum_and_count[1] +
                table.dvi_value_sum_and_count[1]
            )
        return out


@dataclasses.dataclass()
class SummaryTableDroughtWidgets:
    '''Combo boxes and methods used in the drought summary table widget'''
    combo_dataset_drought: data_io.WidgetDataIOSelectTEDatasetExisting
    combo_layer_jrc_vulnerability: data_io.WidgetDataIOSelectTELayerExisting

    def populate(self):
        self.combo_dataset_drought.populate()
        self.combo_layer_jrc_vulnerability.populate()


@dataclasses.dataclass()
class DroughtInputInfo:
    path: Path
    bands: List[models.JobBand]
    indices: List[int]
    years: List[int]


def _get_drought_inputs(
    data_selection_widget: data_io.WidgetDataIOSelectTEDatasetExisting,
    band_name: str,
    sort_property: str = "year"
) -> DroughtInputInfo:
    bands = data_selection_widget.get_bands(band_name)

    sorted_bands = sorted(
        bands,
        key=lambda b: b.band_info.metadata[sort_property]
    )

    years = [b.band_info.metadata[sort_property] for b in sorted_bands]
    indices = [b.band_index for b in sorted_bands]

    return DroughtInputInfo(
        path=data_selection_widget.get_current_data_file(),
        bands=[b.band_info for b in sorted_bands],
        indices=indices,
        years=years
    )


def _get_spi_lag(
    data_selection_widget: data_io.WidgetDataIOSelectTEDatasetExisting
):
    band = data_selection_widget.get_bands(SPI_BAND_NAME)[0]
    return band.band_info.metadata['lag']


@dataclasses.dataclass()
class JRCInputInfo:
    path: Path
    band: models.JobBand
    band_index: int


def _get_jrc_input(
    data_selection_widget: data_io.WidgetDataIOSelectTEDatasetExisting
) -> JRCInputInfo:
    usable_band_info = data_selection_widget.get_current_band()

    return JRCInputInfo(
        path=usable_band_info.path,
        band=usable_band_info.band_info,
        band_index=usable_band_info.band_index
    )


def get_main_drought_summary_job_params(
        task_name: str,
        aoi,
        combo_dataset_drought: data_io.WidgetDataIOSelectTEDatasetExisting,
        combo_layer_jrc_vulnerability: data_io.WidgetDataIOSelectTELayerExisting,
        task_notes: Optional[str] = ""
) -> Dict:

    spi_input = _get_drought_inputs(
        combo_dataset_drought,
        SPI_BAND_NAME
    )
    population_input = _get_drought_inputs(
        combo_dataset_drought,
        POPULATION_BAND_NAME
    )
    spi_lag = _get_spi_lag(combo_dataset_drought)

    jrc_input = _get_jrc_input(
        combo_layer_jrc_vulnerability,
    )

    crosses_180th, geojsons = aoi.bounding_box_gee_geojson()

    return {
        "task_name": task_name,
        "task_notes": task_notes,
        "layer_population_path": str(population_input.path),
        "layer_population_bands": [
            models.JobBand.Schema().dump(b)
            for b in population_input.bands
        ],
        "layer_population_years": population_input.years,
        "layer_population_band_indices": population_input.indices,
        "layer_spi_path": str(spi_input.path),
        "layer_spi_bands": [
            models.JobBand.Schema().dump(b)
            for b in spi_input.bands
        ],
        "layer_spi_band_indices": spi_input.indices,
        "layer_spi_years": spi_input.years,
        "layer_spi_lag": spi_lag,
        "layer_jrc_path": str(jrc_input.path),
        "layer_jrc_band": models.JobBand.Schema().dump(jrc_input.band),
        "layer_jrc_band_index": jrc_input.band_index,
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


def compute_drought_vulnerability(
        drought_job: models.Job,
        area_of_interest: areaofinterest.AOI) -> models.Job:
    """Calculate drought vulnerability indicators and save to disk"""

    job_output_path, _ = utils.get_local_job_output_paths(drought_job)

    summary_table_stable_kwargs = {}

    params = drought_job.params.params

    drought_period = 4

    spi_dfs = _prepare_dfs(
        params['layer_spi_path'],
        params['layer_spi_bands'],
        params['layer_spi_band_indices']
    )

    population_dfs = _prepare_dfs(
        params['layer_population_path'],
        params['layer_population_bands'],
        params['layer_population_band_indices']
    )

    jrc_df = _prepare_dfs(
        params['layer_jrc_path'],
        [params['layer_jrc_band']],
        [params['layer_jrc_band_index']]
    )

    _, wkt_bounding_boxes = area_of_interest.meridian_split(
            "layer", "wkt", warn=False)

    summary_table_stable_kwargs = {
        "wkt_bounding_boxes": wkt_bounding_boxes,
        "compute_bbs_from": params['layer_spi_path'],
        "output_job_path": job_output_path.parent / f"{job_output_path.stem}.json"
    }

    summary_table, out_path = _compute_drought_summary_table(
        **summary_table_stable_kwargs,
        in_dfs=spi_dfs + population_dfs + jrc_df,
        drought_period=drought_period
    )

    out_bands = []
    for period_number, year_initial in enumerate(
        range(
            int(params['layer_spi_years'][0]),
            int(params['layer_spi_years'][-1]),
            drought_period
        )
    ):
        if (year_initial + drought_period - 1) > params['layer_spi_years'][-1]:
            year_final = params['layer_spi_years'][-1]
        else:
            year_final = year_initial + drought_period - 1

        out_bands.append(models.JobBand(
            name="Minimum SPI over period",
            no_data_value=NODATA_VALUE,
            metadata={
                'year_initial': year_initial,
                'year_final': year_final,
                'lag': int(params['layer_spi_lag'])
            },
            activated=True
        ))

        out_bands.append(models.JobBand(
            name="Population density at minimum SPI over period",
            no_data_value=NODATA_VALUE,
            metadata={
                'year_initial': year_initial,
                'year_final': year_final
            },
            activated=True
        ))

    out_df = DataFile(out_path.name, out_bands)

    drought_job.results.bands.extend(out_df.bands)

    # Also save bands to a key file for ease of use in PRAIS
    key_json = job_output_path.parent / f"{job_output_path.stem}_band_key.json"
    with open(key_json, 'w') as f:
        json.dump(DataFile.Schema().dump(out_df), f, indent=4)

    summary_json_output_path = job_output_path.parent / f"{job_output_path.stem}_summary.json"
    save_reporting_json(
        summary_json_output_path,
        summary_table,
        drought_job.params.params,
        drought_job.params.task_name,
        area_of_interest,
        summary_table_stable_kwargs
    )

    summary_table_output_path = job_output_path.parent / f"{job_output_path.stem}_summary.xlsx"
    save_summary_table_excel(
        summary_table_output_path,
        summary_table,
        years=[int(y) for y in params['layer_spi_years']]
    )

    drought_job.results.data_path = out_path
    drought_job.results.other_paths.extend(
        [
            summary_json_output_path,
            summary_table_output_path,
            key_json
        ]
    )
    drought_job.end_date = dt.datetime.now(dt.timezone.utc)
    drought_job.progress = 100

    return drought_job


def _combine_all_bands_into_vrt(in_files: List[Path], out_file: Path):
    '''creates a vrt file combining all bands of in_files

    All bands must have the same extent, resolution, and crs
    '''

    simple_source_raw = '''    <SimpleSource>
        <SourceFilename relativeToVRT="1">{relative_path}</SourceFilename>
        <SourceBand>{source_band_num}</SourceBand>
        <SrcRect xOff="0" yOff="0" xSize="{out_Xsize}" ySize="{out_Ysize}"/>
        <DstRect xOff="0" yOff="0" xSize="{o
        ut_Xsize}" ySize="{out_Ysize}"/>
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
                    line.replace(str(out_file.parents[0]) + '/', '')
                )
    out_file.unlink()
    shutil.copy(str(new_file), str(out_file))

    return True


def _prepare_dfs(
    path,
    band_str_list,
    band_indices
) -> List[DataFile]:
    dfs = []
    for band_str, band_index in zip(band_str_list, band_indices):
        band = models.JobBand(**band_str)
        dfs.append(
            DataFile(
                path=utils.save_vrt(
                    path,
                    band_index
                ),
                bands=[band]
            )
        )
    return dfs


def save_summary_table_excel(
        output_path: Path,
        summary_table: SummaryTableDrought,
        years: List[int]
):
    """Save summary table into an xlsx file on disk"""
    template_summary_table_path = Path(
        __file__).parents[1] / "data/summary_table_drought.xlsx"
    workbook = openpyxl.load_workbook(str(template_summary_table_path))
    _render_drought_workbook(
        workbook,
        summary_table,
        years
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


def _get_population_list_by_drought_class(pop_by_drought, pop_type):
    return reporting.PopulationList(
        'Total population by drought class',
        [
            reporting.Population(
                'Mild drought',
                pop_by_drought.get(1, 0.),
                type=pop_type
            ),
            reporting.Population(
                'Moderate drought',
                pop_by_drought.get(2, 0.),
                type=pop_type
            ),
            reporting.Population(
                'Severe drought',
                pop_by_drought.get(3, 0.),
                type=pop_type
            ),
            reporting.Population(
                'Extreme drought',
                pop_by_drought.get(4, 0.),
                type=pop_type
            ),
            reporting.Population(
                'Non-drought',
                pop_by_drought.get(0, 0.),
                type=pop_type
            ),
            reporting.Population(
                'No data',
                pop_by_drought.get(-32768, 0.),
                type=pop_type
            )
        ]
    )

def save_reporting_json(
    output_path: Path,
    st: SummaryTableDrought,
    params: dict,
    task_name: str,
    aoi: areaofinterest.AOI,
    summary_table_kwargs: dict
):

    drought_tier_one = {}
    drought_tier_two = {}

    for n, year in enumerate(range(
        int(params['layer_spi_years'][0]),
        int(params['layer_spi_years'][-1]) + 1
    )):

        drought_tier_one[year] = reporting.AreaList(
            "Area by drought class",
            'sq km',
            [
                reporting.Area(
                    'Mild drought',
                    st.annual_area_by_drought_class[n].get(1, 0.)),
                reporting.Area(
                    'Moderate drought',
                    st.annual_area_by_drought_class[n].get(2, 0.)),
                reporting.Area(
                    'Severe drought',
                    st.annual_area_by_drought_class[n].get(3, 0.)),
                reporting.Area(
                    'Extreme drought',
                    st.annual_area_by_drought_class[n].get(4, 0.)),
                reporting.Area(
                    'Non-drought',
                    st.annual_area_by_drought_class[n].get(0, 0.)),
                reporting.Area(
                    'No data',
                    st.annual_area_by_drought_class[n].get(-32768, 0.))
            ]
        )

        drought_tier_two[year] = {
            'Total population': _get_population_list_by_drought_class(
                st.annual_population_by_drought_class_total[n],
                "Total population"
            )
        }
        if st.annual_population_by_drought_class_male:
            drought_tier_two[year]['Male population'] = _get_population_list_by_drought_class(
                _get_population_list_by_drought_class(
                    st.annual_population_by_drought_class_male[n],
                    "Male population"
                )
            )
        if st.annual_population_by_drought_class_female:
            drought_tier_two[year]['Female population'] = _get_population_list_by_drought_class(
                _get_population_list_by_drought_class(
                    st.annual_population_by_drought_class_female[n],
                    "Female population"
                )
            )

    drought_tier_three = {
        2018: reporting.Value(
            'Mean value',
            st.dvi_value_sum_and_count[0] / st.dvi_value_sum_and_count[1]
        )
    }

    ##########################################################################
    # Format final JSON output
    te_summary = reporting.TrendsEarthDroughtSummary(
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
                    name=task_name,  # TODO replace this with area of interest name once implemented in TE
                    geojson=aoi.get_geojson(),
                    crs_wkt=aoi.get_crs_wkt()
                )
            ),

            drought=reporting.DroughtReport(
                tier_one=drought_tier_one,
                tier_two=drought_tier_two,
                tier_three=drought_tier_three
            )
        )

    try:
        te_summary_json = json.loads(
            reporting.TrendsEarthDroughtSummary.Schema().dumps(te_summary)
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
class DroughtSummaryWorkerParams(SchemaBase):
    in_df: DataFile
    out_file: str
    drought_period: int
    mask_file: str


def _process_block(
    params: DroughtSummaryWorkerParams,
    in_array,
    mask,
    xoff: int,
    yoff: int,
    cell_areas_raw
) -> Tuple[SummaryTableDrought, Dict]:

    write_arrays = {}

    # Make an array of the same size as the input arrays containing
    # the area of each cell (which is identical for all cells in a
    # given row - cell areas only vary among rows)
    cell_areas = np.repeat(
        cell_areas_raw, mask.shape[1], axis=1
    ).astype(np.float64)

    spi_rows = params.in_df.array_rows_for_name(SPI_BAND_NAME)
    pop_rows = params.in_df.array_rows_for_name(POPULATION_BAND_NAME)

    assert len(spi_rows) == len(pop_rows)

    # Calculate well annual totals of area and population exposed to drought
    annual_area_by_drought_class = []
    annual_population_by_drought_class_total = []
    annual_population_by_drought_class_male = []
    annual_population_by_drought_class_female = []
    for spi_row, pop_row in zip(spi_rows, pop_rows):
        a_drought_class = drought_class(in_array[spi_row, :, :])

        annual_area_by_drought_class.append(
            zonal_total(
                a_drought_class,
                cell_areas,
                mask
            )
        )

        a_pop = in_array[pop_row, :, :]
        a_pop_masked = a_pop.copy()
        # Account for scaling and convert from density
        a_pop_masked = a_pop * 10. * cell_areas
        a_pop_masked[a_pop == NODATA_VALUE] = 0
        annual_population_by_drought_class_total.append(
            zonal_total(
                a_drought_class,
                a_pop_masked,
                mask
            )
        )
    
    # Calculate minimum SPI in blocks of length (in years) defined by 
    # params.drought_period, and save the spi at that point as well as 
    # population that was exposed to it at that point
    for period_number, first_row in enumerate(
            range(0, len(spi_rows), params.drought_period)):
        if (first_row + params.drought_period - 1) > len(spi_rows):
            last_row = len(spi_rows)
        else:
            last_row = first_row + params.drought_period - 1

        spis = in_array[spi_rows[first_row:last_row], :, :]
        pops = in_array[pop_rows[first_row:last_row], :, :].copy()

        # Max drought is at minimum SPI
        min_indices = np.expand_dims(np.argmin(spis, axis=0), axis=0)
        max_drought = np.take_along_axis(spis, min_indices, axis=0)
        pop_at_max_drought = np.take_along_axis(pops, min_indices, axis=0)

        pop_at_max_drought_masked = pop_at_max_drought.copy()
        # Account for scaling and convert from density
        pop_at_max_drought_masked = pop_at_max_drought * 10. * cell_areas
        pop_at_max_drought_masked[pop_at_max_drought == NODATA_VALUE] = 0

        # Add one as output band numbers start at 1, not zero
        write_arrays[2*period_number + 1] = {
            'array': max_drought.squeeze(),  # remove zero dim of len 1
            'xoff': xoff,
            'yoff': yoff
        }

        # Add two as output band numbers start at 1, not zero, and this is the 
        # second band for this period
        write_arrays[2*period_number + 2] = {
            'array': pop_at_max_drought_masked.squeeze(),
            'xoff': xoff,
            'yoff': yoff
        }

    jrc_row = params.in_df.array_row_for_name(JRC_BAND_NAME)
    dvi_value_sum_and_count = jrc_sum_and_count(in_array[jrc_row, :, :], mask)

    return (
        SummaryTableDrought(
            annual_area_by_drought_class,
            annual_population_by_drought_class_total,
            annual_population_by_drought_class_male,
            annual_population_by_drought_class_female,
            dvi_value_sum_and_count
        ),
        write_arrays
    )


class DroughtSummaryWorker(worker.AbstractWorker):
    def __init__(
        self,
        params: DroughtSummaryWorkerParams
    ):

        worker.AbstractWorker.__init__(self)

        self.params = params

    def work(self):
        self.toggle_show_progress.emit(True)
        self.toggle_show_cancel.emit(True)

        mask_ds = gdal.Open(self.params.mask_file)
        band_mask = mask_ds.GetRasterBand(1)

        src_ds = gdal.Open(str(self.params.in_df.path))
        spi_band_1 = src_ds.GetRasterBand(
            self.params.in_df.array_rows_for_name(SPI_BAND_NAME)[0] + 1
        )
        block_sizes = spi_band_1.GetBlockSize()
        xsize = spi_band_1.XSize
        ysize = spi_band_1.YSize

        x_block_size = block_sizes[0]
        y_block_size = block_sizes[1]

        # Need two output bands for each four year period, plus one for the JRC 
        # layer
        n_out_bands = int(
            2*np.ceil(
                len(
                    self.params.in_df.array_rows_for_name(SPI_BAND_NAME)
                ) / self.params.drought_period
            ) + 1
        )

        # Setup output file for max drought and population counts
        driver = gdal.GetDriverByName("GTiff")
        dst_ds = driver.Create(
            self.params.out_file,
            xsize,
            ysize,
            n_out_bands,
            gdal.GDT_Int16,
            options=['COMPRESS=LZW']
        )
        src_gt = src_ds.GetGeoTransform()
        dst_ds.SetGeoTransform(src_gt)
        dst_srs = osr.SpatialReference()
        dst_srs.ImportFromWkt(src_ds.GetProjectionRef())
        dst_ds.SetProjection(dst_srs.ExportToWkt())

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
                    dst_ds.GetRasterBand(key).WriteArray(**value)

                n += 1
            if self.killed:
                break

            lat += pixel_height * win_ysize

        # pr.disable()
        # pr.dump_stats('calculate_drought_stats')

        if self.killed:
            del dst_ds
            os.remove(self.params.out_file)
            return None
        else:
            self.progress.emit(100)
            return _accumulate_summary_tables(out)


def _render_drought_workbook(
    template_workbook,
    summary_table: SummaryTableDrought,
    years: List[int]
):
    _write_drought_area_sheet(
        template_workbook["Area under drought by year"],
        summary_table,
        years
    )

    _write_drought_pop_total_sheet(
        template_workbook["Pop under drought (total)"],
        summary_table,
        years
    )

    _write_dvi_sheet(
        template_workbook["Drought Vulnerability Index"],
        summary_table,
        years
    )

    return template_workbook


def _calculate_summary_table(
        bbox,
        pixel_aligned_bbox,
        in_dfs: List[DataFile],
        output_tif_path: Path,
        mask_worker_process_name,
        drought_worker_process_name,
        drought_period: int
) -> Tuple[
    Optional[SummaryTableDrought],
    str
]:
    # Combine all raster into a VRT and crop to the AOI
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
        indic_vrt
    )

    error_message = ""
    if mask_worker.success:
        in_df = _combine_data_files(indic_vrt, in_dfs)

        log(u'Calculating summary table and saving to: {}'.format(output_tif_path))
        drought_worker = worker.StartWorker(
            DroughtSummaryWorker,
            drought_worker_process_name,
            DroughtSummaryWorkerParams(
                in_df=in_df,
                out_file=str(output_tif_path),
                mask_file=mask_vrt,
                drought_period = drought_period
            )
        )
        if not drought_worker.success:
            if drought_worker.was_killed():
                error_message = "Cancelled calculation of summary table."
            else:
                error_message = "Error calculating summary table."
            result = None
        else:
            result = drought_worker.get_return()

    else:
        error_message = "Error creating mask."
        result = None

    return result, error_message


def _compute_drought_summary_table(
    wkt_bounding_boxes,
    in_dfs,
    compute_bbs_from,
    output_job_path: Path,
    drought_period: int
) -> Tuple[SummaryTableDrought, Path, Path]:
    """Computes summary table and the output tif file(s)"""
    bbs = areaofinterest.get_aligned_output_bounds(
        compute_bbs_from,
        wkt_bounding_boxes
    )
    output_name_pattern = {
        1: f"{output_job_path.stem}" + ".tif",
        2: f"{output_job_path.stem}" + "_{index}.tif"
    }[len(wkt_bounding_boxes)]
    mask_name_fragment = {
        1: "Generating mask",
        2: "Generating mask (part {index} of 2)",
    }[len(wkt_bounding_boxes)]
    drought_name_fragment = {
        1: "Calculating summary table",
        2: "Calculating summary table (part {index} of 2)",
    }[len(wkt_bounding_boxes)]

    summary_tables = []
    out_paths = []
    for index, ( 
        wkt_bounding_box,
        pixel_aligned_bbox
    ) in enumerate(zip(wkt_bounding_boxes, bbs), start=1):
        out_path = output_job_path.parent / output_name_pattern.format(
            index=index
        )
        out_paths.append(out_path)
        result, error_message = _calculate_summary_table(
            bbox=wkt_bounding_box,
            pixel_aligned_bbox=pixel_aligned_bbox,
            output_tif_path=out_path,
            mask_worker_process_name=mask_name_fragment.format(index=index),
            drought_worker_process_name=drought_name_fragment.format(index=index),
            in_dfs=in_dfs,
            drought_period=drought_period
        )
        if result is None:
            raise RuntimeError(error_message)
        else:
            summary_tables.append(result)

    summary_table = _accumulate_summary_tables(summary_tables)

    if len(out_paths) > 1:
        out_path = output_job_path.parent / f"{output_job_path.stem}.vrt"
        gdal.BuildVRT(str(out_path), [str(p) for p in out_paths])
    else:
        out_path = out_paths[0]

    return summary_table, out_path


def _get_col_for_drought_class(
    annual_values_by_drought,
    drought_code
):
    out = []
    for values_by_drought in annual_values_by_drought:
        out.append(values_by_drought.get(drought_code, 0.))
    return np.array(out)


def _write_dvi_sheet(
    sheet,
    st: SummaryTableDrought,
    years
):

    # Make this more informative when fuller DVI calculations are available...
    cell = sheet.cell(6, 2)
    cell.value = 2018
    cell = sheet.cell(6, 3)
    cell.value = st.dvi_value_sum_and_count[0] / st.dvi_value_sum_and_count[1]

    utils.maybe_add_image_to_sheet(
        "trends_earth_logo_bl_300width.png", sheet, "H1")


def _write_drought_area_sheet(
    sheet,
    st: SummaryTableDrought,
    years
):
    summary.write_col_to_sheet(
        sheet,
        np.array(years),
        2, 7
    )
    summary.write_col_to_sheet(
        sheet,
        _get_col_for_drought_class(
            st.annual_area_by_drought_class, 1),
        4, 7
    )
    summary.write_col_to_sheet(
        sheet,
        _get_col_for_drought_class(
            st.annual_area_by_drought_class, 2),
        6, 7
    )
    summary.write_col_to_sheet(
        sheet,
        _get_col_for_drought_class(
            st.annual_area_by_drought_class, 3),
        8, 7
    )
    summary.write_col_to_sheet(
        sheet,
        _get_col_for_drought_class(
            st.annual_area_by_drought_class, 4),
        10, 7
    )
    summary.write_col_to_sheet(
        sheet,
        _get_col_for_drought_class(
            st.annual_area_by_drought_class, 0),
        12, 7
    )
    summary.write_col_to_sheet(
        sheet,
        _get_col_for_drought_class(
            st.annual_area_by_drought_class, -32768),
        14, 7
    )
    utils.maybe_add_image_to_sheet(
        "trends_earth_logo_bl_300width.png", sheet, "L1")


def _write_drought_pop_total_sheet(
    sheet,
    st: SummaryTableDrought,
    years
):
    summary.write_col_to_sheet(
        sheet,
        np.array(years),
        2, 7
    )
    summary.write_col_to_sheet(
        sheet,
        _get_col_for_drought_class(
            st.annual_population_by_drought_class_total, 1),
        4, 7
    )
    summary.write_col_to_sheet(
        sheet,
        _get_col_for_drought_class(
            st.annual_population_by_drought_class_total, 2),
        6, 7
    )
    summary.write_col_to_sheet(
        sheet,
        _get_col_for_drought_class(
            st.annual_population_by_drought_class_total, 3),
        8, 7
    )
    summary.write_col_to_sheet(
        sheet,
        _get_col_for_drought_class(
            st.annual_population_by_drought_class_total, 4),
        10, 7
    )
    summary.write_col_to_sheet(
        sheet,
        _get_col_for_drought_class(
            st.annual_population_by_drought_class_total, 0),
        12, 7
    )
    summary.write_col_to_sheet(
        sheet,
        _get_col_for_drought_class(
            st.annual_population_by_drought_class_total, -32768),
        14, 7
    )
    utils.maybe_add_image_to_sheet(
        "trends_earth_logo_bl_300width.png", sheet, "L1")
