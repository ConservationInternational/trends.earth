import dataclasses
import json
from pathlib import Path
from typing import Dict
from typing import List
from typing import Optional

from te_algorithms.gdal.drought import summarise_drought_vulnerability
from te_schemas.aoi import AOI
from te_schemas.results import Band as JobBand

from .. import data_io
from .. import tr
from .. import worker
from ..jobs.models import Job

NODATA_VALUE = -32768
MASK_VALUE = -32767

POPULATION_BAND_NAME = "Population (density, persons per sq km / 10)"
SPI_BAND_NAME = "Standardized Precipitation Index (SPI)"


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
    bands: List[JobBand]
    indices: List[int]
    years: List[int]


def _get_drought_inputs(
    data_selection_widget: data_io.WidgetDataIOSelectTEDatasetExisting,
    band_name: str,
    sort_property: str = "year"
) -> DroughtInputInfo:
    bands = data_selection_widget.get_bands(band_name)

    sorted_bands = sorted(
        bands, key=lambda b: b.band_info.metadata[sort_property]
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
    band: JobBand
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

    spi_input = _get_drought_inputs(combo_dataset_drought, SPI_BAND_NAME)
    population_input = _get_drought_inputs(
        combo_dataset_drought, POPULATION_BAND_NAME
    )
    spi_lag = _get_spi_lag(combo_dataset_drought)

    jrc_input = _get_jrc_input(combo_layer_jrc_vulnerability, )

    water_mask_input = _get_water_mask_input(combo_dataset_drought, )

    crosses_180th, geojsons = aoi.bounding_box_gee_geojson()

    return {
        "task_name":
        task_name,
        "task_notes":
        task_notes,
        "layer_population_path":
        str(population_input.path),
        "layer_population_bands":
        [JobBand.Schema().dump(b) for b in population_input.bands],
        "layer_population_years":
        population_input.years,
        "layer_population_band_indices":
        population_input.indices,
        "layer_spi_path":
        str(spi_input.path),
        "layer_spi_bands": [JobBand.Schema().dump(b) for b in spi_input.bands],
        "layer_spi_band_indices":
        spi_input.indices,
        "layer_spi_years":
        spi_input.years,
        "layer_spi_lag":
        spi_lag,
        "layer_jrc_path":
        str(jrc_input.path),
        "layer_jrc_band":
        JobBand.Schema().dump(jrc_input.band),
        "layer_jrc_band_index":
        jrc_input.band_index,
        "layer_water_mask_path":
        str(water_mask_input.path),
        "layer_water_mask_band":
        JobBand.Schema().dump(water_mask_input.band),
        "layer_water_mask_band_index":
        water_mask_input.band_index,
        "crs":
        aoi.get_crs_dst_wkt(),
        "geojsons":
        json.dumps(geojsons),
        "crosses_180th":
        crosses_180th,
    }


# class DroughtSummaryWorker(worker.AbstractWorker, DroughtSummary):
#     def __init__(
#         self,
#         params: DroughtSummaryParams
#     ):
#         self.params = params
#
#         worker.AbstractWorker.__init__(self)
#         DroughtSummary.__init__(self)
#
#     def emit_progress(self, frac):
#         self.progress.emit(frac * 100)
#
#     def is_killed(self):
#         return self.killed
#
#     def work(self):
#         self.toggle_show_progress.emit(True)
#         self.toggle_show_cancel.emit(True)
#
#         out = self.process_lines(
#             self.get_line_params()
#         )
#
#         if self.killed:
#             os.remove(self.params.out_file)
#             return None
#         else:
#             self.emit_progress(100)
#             return out
#
#     drought_worker = worker.StartWorker(
#         DroughtSummary,
#         drought_worker_process_name,
#         DroughtSummaryParams(
#             in_df=in_df,
#             out_file=str(output_tif_path),
#             mask_file=mask_vrt,
#             drought_period=drought_period
#         )
#     )


def compute_drought_vulnerability(
    drought_job: Job, aoi: AOI, job_output_path: Path,
    dataset_output_path: Path
) -> Job:
    """Calculate drought vulnerability indicators and save to disk"""

    return summarise_drought_vulnerability(
        drought_job, AOI(aoi.get_geojson()), job_output_path
    )
