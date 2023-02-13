import dataclasses
import enum
import json
from pathlib import Path
from typing import Dict
from typing import List
from typing import Optional
from typing import Union

import te_algorithms.gdal.land_deg.config as ld_config
from qgis.PyQt import QtWidgets
from te_algorithms.gdal.land_deg.land_deg import summarise_land_degradation
from te_schemas.aoi import AOI
from te_schemas.productivity import ProductivityMode
from te_schemas.results import Band as JobBand

from .. import data_io
from ..jobs.models import Job

NODATA_VALUE = -32768
MASK_VALUE = -32767


class PopulationMode(enum.Enum):
    BySex = "Population disaggregated by sex"
    Total = "Total population"


@dataclasses.dataclass()
class SummaryTableLDWidgets:
    """Combo boxes and methods used in the SDG 15.3.1 summary table widget"""

    combo_datasets: data_io.WidgetDataIOSelectTEDatasetExisting
    combo_layer_traj: data_io.WidgetDataIOSelectTELayerExisting
    combo_layer_traj_label: QtWidgets.QLabel
    combo_layer_perf: data_io.WidgetDataIOSelectTELayerExisting
    combo_layer_perf_label: QtWidgets.QLabel
    combo_layer_state: data_io.WidgetDataIOSelectTELayerExisting
    combo_layer_state_label: QtWidgets.QLabel
    combo_layer_lpd: data_io.WidgetDataIOSelectTELayerImport
    combo_layer_lpd_label: QtWidgets.QLabel
    combo_layer_lc: data_io.WidgetDataIOSelectTELayerExisting
    combo_layer_soc: data_io.WidgetDataIOSelectTELayerExisting
    combo_layer_pop_total: data_io.WidgetDataIOSelectTELayerExisting
    combo_layer_pop_male: data_io.WidgetDataIOSelectTELayerExisting
    combo_layer_pop_female: data_io.WidgetDataIOSelectTELayerExisting
    radio_lpd_te: QtWidgets.QRadioButton

    def __post_init__(self):
        self.radio_lpd_te.toggled.connect(self.radio_lpd_te_toggled)
        self.radio_lpd_te_toggled()
        self.combo_datasets.job_selected.connect(self.set_combo_selections_from_job_id)

    def populate(self):
        self.populate_layer_combo_boxes()
        self.combo_datasets.populate()

    def radio_lpd_te_toggled(self):
        if self.radio_lpd_te.isChecked():
            self.combo_layer_traj.show()
            self.combo_layer_traj_label.show()
            self.combo_layer_perf.show()
            self.combo_layer_perf_label.show()
            self.combo_layer_state.show()
            self.combo_layer_state_label.show()
            self.combo_layer_lpd.hide()
            self.combo_layer_lpd_label.hide()
        else:
            self.combo_layer_traj.hide()
            self.combo_layer_traj_label.hide()
            self.combo_layer_perf.hide()
            self.combo_layer_perf_label.hide()
            self.combo_layer_state.hide()
            self.combo_layer_state_label.hide()
            self.combo_layer_lpd.show()
            self.combo_layer_lpd_label.show()

    def populate_layer_combo_boxes(self):
        self.combo_layer_lpd.populate()
        self.combo_layer_traj.populate()
        self.combo_layer_perf.populate()
        self.combo_layer_state.populate()
        self.combo_layer_lc.populate()
        self.combo_layer_soc.populate()
        self.combo_layer_pop_total.populate()
        self.combo_layer_pop_male.populate()
        self.combo_layer_pop_female.populate()

    def set_combo_selections_from_job_id(self, job_id):
        self.combo_layer_lpd.set_index_from_job_id(job_id)
        self.combo_layer_traj.set_index_from_job_id(job_id)
        self.combo_layer_perf.set_index_from_job_id(job_id)
        self.combo_layer_state.set_index_from_job_id(job_id)
        self.combo_layer_lc.set_index_from_job_id(job_id)
        self.combo_layer_soc.set_index_from_job_id(job_id)
        self.combo_layer_pop_total.set_index_from_job_id(job_id)
        self.combo_layer_pop_female.set_index_from_job_id(job_id)
        self.combo_layer_pop_male.set_index_from_job_id(job_id)


@dataclasses.dataclass()
class LdnInputInfo:
    path: Path
    main_band: JobBand
    main_band_index: int
    aux_bands: List[JobBand]
    aux_band_indexes: List[int]
    years: List[int]


@dataclasses.dataclass()
class PopInputInfo:
    paths: List[Path]
    bands: List[JobBand]
    band_indices: List[int]
    years: List[int]


def _get_ld_input_period(
    data_selection_widget: data_io.WidgetDataIOSelectTELayerExisting,
    year_initial_field: str = "year_initial",
    year_final_field: str = "year_final",
) -> LdnInputInfo:
    band_info = data_selection_widget.get_current_band().band_info

    return {
        "year_initial": band_info.metadata[year_initial_field],
        "year_final": band_info.metadata[year_final_field],
    }


def _get_ld_inputs(
    data_selection_widget: data_io.WidgetDataIOSelectTELayerExisting,
    aux_band_name: Union[str, list],
    sort_property: str = "year",
) -> LdnInputInfo:
    """Used to get main band and set of aux bands associated with a combo box"""
    if isinstance(aux_band_name, str):
        # Some aux_bands may have multiple potential names (this happens with land
        # cover for example, which can be "Land cover (7 class)" or just "Land cover").
        # This function assumes a list, so convert a single band name to a length 1 list.
        aux_band_name = [aux_band_name]
    usable_band_info = data_selection_widget.get_current_band()
    main_band = usable_band_info.band_info
    main_band_index = usable_band_info.band_index
    aux_bands = []

    for band_index, job_band in enumerate(
        usable_band_info.job.results.get_bands(), start=1
    ):
        if job_band.name in aux_band_name:
            aux_bands.append((job_band, band_index))
    sorted_aux_bands = sorted(aux_bands, key=lambda i: i[0].metadata[sort_property])
    aux_bands = [info[0] for info in sorted_aux_bands]
    aux_band_indexes = [info[1] for info in sorted_aux_bands]
    years = [i[0].metadata[sort_property] for i in sorted_aux_bands]

    return LdnInputInfo(
        path=usable_band_info.path,
        main_band=main_band,
        main_band_index=main_band_index,
        aux_bands=aux_bands,
        aux_band_indexes=aux_band_indexes,
        years=years,
    )


def _get_pop_inputs(
    pop_mode,
    total_pop_selection_widget: data_io.WidgetDataIOSelectTELayerExisting,
    male_pop_selection_widget: data_io.WidgetDataIOSelectTELayerExisting,
    female_pop_selection_widget: data_io.WidgetDataIOSelectTELayerExisting,
) -> PopInputInfo:
    """Used to get pop band(s) from combo boxes"""

    if pop_mode == PopulationMode.Total.value:
        total_pop_band_info = total_pop_selection_widget.get_current_band()
        bands = [total_pop_band_info.band_info]
        paths = [total_pop_band_info.path]
        band_indices = [total_pop_band_info.band_index]
        years = [total_pop_band_info.band_info.metadata["year"]]

    elif pop_mode == PopulationMode.BySex.value:
        male_pop_band_info = male_pop_selection_widget.get_current_band()
        female_pop_band_info = female_pop_selection_widget.get_current_band()
        bands = [male_pop_band_info.band_info, female_pop_band_info.band_info]
        paths = [
            male_pop_band_info.path,
            female_pop_band_info.path,
        ]
        band_indices = [male_pop_band_info.band_index, female_pop_band_info.band_index]
        years = [
            male_pop_band_info.band_info.metadata["year"],
            female_pop_band_info.band_info.metadata["year"],
        ]
    else:
        raise Exception("Unknown population mode {pop_mode}")

    return PopInputInfo(
        paths=paths, bands=bands, band_indices=band_indices, years=years
    )


def _get_ld_input_aux_band(
    data_selection_widget: data_io.WidgetDataIOSelectTELayerExisting, aux_band_name: str
) -> LdnInputInfo:
    """Used to get a single aux band associated with a combo box"""
    usable_band_info = data_selection_widget.get_current_band()

    aux_bands = []

    for band_index, job_band in enumerate(
        usable_band_info.job.results.get_bands(), start=1
    ):
        if job_band.name == aux_band_name:
            aux_bands.append((job_band, band_index))
    assert len(aux_bands) == 1
    aux_band = aux_bands[0]

    return {
        "path": usable_band_info.path,
        "band": aux_band[0],
        "band_index": aux_band[1],
    }


def get_main_sdg_15_3_1_job_params(
    task_name: str,
    aoi,
    prod_mode: str,
    pop_mode: str,
    period_name: str,
    combo_layer_lc: data_io.WidgetDataIOSelectTELayerExisting,
    combo_layer_soc: data_io.WidgetDataIOSelectTELayerExisting,
    combo_layer_traj: data_io.WidgetDataIOSelectTELayerExisting,
    combo_layer_perf: data_io.WidgetDataIOSelectTELayerExisting,
    combo_layer_state: data_io.WidgetDataIOSelectTELayerExisting,
    combo_layer_lpd: data_io.WidgetDataIOSelectTELayerExisting,
    combo_layer_pop_total: data_io.WidgetDataIOSelectTELayerExisting,
    combo_layer_pop_male: data_io.WidgetDataIOSelectTELayerExisting,
    combo_layer_pop_female: data_io.WidgetDataIOSelectTELayerExisting,
    task_notes: Optional[str] = "",
) -> Dict:
    land_cover_inputs = _get_ld_inputs(combo_layer_lc, ld_config.LC_BAND_NAME)
    land_cover_transition_input = _get_ld_input_aux_band(
        combo_layer_lc, ld_config.LC_TRANS_BAND_NAME
    )
    soil_organic_carbon_inputs = _get_ld_inputs(
        combo_layer_soc, ld_config.SOC_BAND_NAME
    )
    population_input = _get_pop_inputs(
        pop_mode, combo_layer_pop_total, combo_layer_pop_male, combo_layer_pop_female
    )

    lc_deg_years = _get_ld_input_period(combo_layer_lc)
    soc_deg_years = _get_ld_input_period(combo_layer_soc)

    crosses_180th, geojsons = aoi.bounding_box_gee_geojson()

    params = {
        "task_name": task_name,
        "task_notes": task_notes,
        "prod_mode": prod_mode,
        "layer_lc_path": str(land_cover_inputs.path),
        "layer_lc_deg_band": JobBand.Schema().dump(land_cover_inputs.main_band),
        "layer_lc_deg_band_index": land_cover_inputs.main_band_index,
        "layer_lc_deg_years": lc_deg_years,
        "layer_lc_aux_bands": [
            JobBand.Schema().dump(b) for b in land_cover_inputs.aux_bands
        ],
        "layer_lc_aux_band_indexes": land_cover_inputs.aux_band_indexes,
        "layer_lc_years": land_cover_inputs.years,
        "layer_lc_trans_band": JobBand.Schema().dump(
            land_cover_transition_input["band"]
        ),
        "layer_lc_trans_path": str(land_cover_transition_input["path"]),
        "layer_lc_trans_band_index": land_cover_transition_input["band_index"],
        "layer_soc_path": str(soil_organic_carbon_inputs.path),
        "layer_soc_deg_band": JobBand.Schema().dump(
            soil_organic_carbon_inputs.main_band
        ),
        "layer_soc_deg_years": soc_deg_years,
        "layer_soc_deg_band_index": soil_organic_carbon_inputs.main_band_index,
        "layer_soc_aux_bands": [
            JobBand.Schema().dump(b) for b in soil_organic_carbon_inputs.aux_bands
        ],
        "layer_soc_aux_band_indexes": soil_organic_carbon_inputs.aux_band_indexes,
        "layer_soc_years": soil_organic_carbon_inputs.years,
        "layer_population_paths": [str(p) for p in population_input.paths],
        "layer_population_bands": [
            JobBand.Schema().dump(b) for b in population_input.bands
        ],
        "layer_population_band_indexes": population_input.band_indices,
        "crs": aoi.get_crs_dst_wkt(),
        "geojsons": json.dumps(geojsons),
        "crosses_180th": crosses_180th,
    }

    params["periods"] = {
        "land_cover": params["layer_lc_deg_years"],
        "soc": params["layer_soc_deg_years"],
    }

    if prod_mode == ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value:
        traj_band_info = combo_layer_traj.get_current_band()
        traj_band = JobBand.Schema().dump(traj_band_info.band_info)
        traj_years = _get_ld_input_period(combo_layer_traj)
        perf_band_info = combo_layer_perf.get_current_band()
        perf_band = JobBand.Schema().dump(perf_band_info.band_info)
        state_band_info = combo_layer_state.get_current_band()
        state_band = JobBand.Schema().dump(state_band_info.band_info)

        params.update(
            {
                "layer_traj_path": str(traj_band_info.path),
                "layer_traj_band": traj_band,
                "layer_traj_years": traj_years,
                "layer_traj_band_index": traj_band_info.band_index,
                "layer_perf_band": perf_band,
                "layer_perf_path": str(perf_band_info.path),
                "layer_perf_band_index": perf_band_info.band_index,
                "layer_state_path": str(state_band_info.path),
                "layer_state_band": state_band,
                "layer_state_band_index": state_band_info.band_index,
            }
        )
        params["periods"]["productivity"] = params["layer_traj_years"]

    elif prod_mode in (
        ProductivityMode.JRC_5_CLASS_LPD.value,
        ProductivityMode.FAO_WOCAT_5_CLASS_LPD.value,
    ):
        lpd_band_info = combo_layer_lpd.get_current_band()
        lpd_band = lpd_band_info.band_info

        lpd_years = _get_ld_input_period(combo_layer_lpd)

        params.update(
            {
                "layer_lpd_path": str(lpd_band_info.path),
                "layer_lpd_years": lpd_years,
                "layer_lpd_band": JobBand.Schema().dump(lpd_band),
                "layer_lpd_band_index": lpd_band_info.band_index,
            }
        )
        params["periods"]["productivity"] = params["layer_lpd_years"]
    else:
        raise Exception(f"Unknown productivity mode {prod_mode}")

    # Add in period start/end if it isn't already in the parameters
    # (wouldn't be if these layers were all run individually and not
    # with the all-in-one tool)

    if "period" not in params:
        params["period"] = {
            "name": period_name,
            "year_initial": params["periods"]["productivity"]["year_initial"],
            "year_final": params["periods"]["productivity"]["year_final"],
        }

    return params


def compute_ldn(
    ldn_job: Job, aoi: AOI, job_output_path: Path, dataset_output_path: Path
) -> Job:
    """Calculate final SDG 15.3.1 indicator and save to disk"""

    return summarise_land_degradation(
        ldn_job, AOI(aoi.get_geojson()), job_output_path, n_cpus=1
    )
