"""Dialog configuration for the separate SDG sub-indicator pipeline."""

from qgis.PyQt import QtCore
from te_algorithms.gdal.land_deg import config as ld_config

from .harness import layer_matches_job, select_dataset_by_job_id

BASELINE_START = 2000
PRODUCTIVITY_START = 2001
BASELINE_END = 2015
STATE_BASELINE_END = 2012


def check_subindicator_bands(chain, bands):
    required = {
        "productivity": (
            (ld_config.TRAJ_BAND_NAME,),
            (ld_config.PERF_BAND_NAME,),
            (ld_config.STATE_BAND_NAME,),
        ),
        "land_cover": (
            (ld_config.LC_DEG_BAND_NAME,),
            tuple(ld_config.LC_BAND_NAME),
            (ld_config.LC_TRANS_BAND_NAME,),
        ),
        "soc": ((ld_config.SOC_DEG_BAND_NAME,), (ld_config.SOC_BAND_NAME,)),
    }
    missing = [
        " / ".join(alternatives)
        for alternatives in required[chain]
        if not any(name in bands for name in alternatives)
    ]
    if missing:
        raise AssertionError(
            f"{chain} results missing required bands: {', '.join(missing)}"
        )


def set_year(widget, year):
    widget.setDate(QtCore.QDate(year, 1, 1))
    if widget.date().year() != year:
        raise ValueError(f"{widget.objectName()} does not support year {year}")


def configure_productivity(dlg):
    dlg.mode_te_prod.setChecked(True)
    dataset = "MODIS (MOD13Q1, annual)"
    index = dlg.dataset_ndvi.findText(dataset)
    if index < 0:
        raise LookupError(f"NDVI dataset {dataset!r} is not available")
    dlg.dataset_ndvi.setCurrentIndex(index)
    methods = [
        name
        for name, config in dlg.trajectory_functions.items()
        if config["params"]["trajectory_method"] == "ndvi_trend"
    ]
    if len(methods) != 1:
        raise LookupError(f"Expected one NDVI trend method, found {methods}")
    dlg.traj_indic.setCurrentText(methods[0])
    for group in (dlg.groupBox_traj, dlg.groupBox_perf, dlg.groupBox_state):
        group.setChecked(True)
    for widget, year in (
        (dlg.traj_year_start, PRODUCTIVITY_START),
        (dlg.traj_year_end, BASELINE_END),
        (dlg.perf_year_start, PRODUCTIVITY_START),
        (dlg.perf_year_end, BASELINE_END),
        (dlg.state_year_bl_start, PRODUCTIVITY_START),
        (dlg.state_year_bl_end, STATE_BASELINE_END),
        (dlg.state_year_tg_start, STATE_BASELINE_END + 1),
        (dlg.state_year_tg_end, BASELINE_END),
    ):
        set_year(widget, year)


def configure_land_cover(dlg):
    set_year(dlg.lc_setup_widget.initial_year_de, BASELINE_START)
    set_year(dlg.lc_setup_widget.target_year_de, BASELINE_END)


def configure_soc(dlg):
    configure_land_cover(dlg)
    dlg.fl_radio_default.setChecked(True)
    dlg.download_annual_lc.setChecked(True)
    dlg.groupBox_custom_SOC.setChecked(False)


def select_separate_inputs(dlg, productivity, land_cover, soc, population):
    """Select and verify provenance of every input to the baseline calculation."""
    dlg.checkBox_progress_period.setChecked(False)
    dlg.radio_lpd_te.setChecked(True)
    dlg.populate_combos()
    widgets = dlg.combo_boxes["baseline"]
    select_dataset_by_job_id(widgets.combo_datasets, population.id)
    widgets.set_combo_selections_from_job_id(population.id)
    for label, combo, job in (
        ("trajectory", widgets.combo_layer_traj, productivity),
        ("performance", widgets.combo_layer_perf, productivity),
        ("state", widgets.combo_layer_state, productivity),
        ("land cover", widgets.combo_layer_lc, land_cover),
        ("soil organic carbon", widgets.combo_layer_soc, soc),
    ):
        if not combo.set_index_from_job_id(job.id) or not layer_matches_job(
            combo, job.id
        ):
            raise LookupError(f"No {label} layer from job {job.id}")
    by_sex = layer_matches_job(
        widgets.combo_layer_pop_male, population.id
    ) and layer_matches_job(widgets.combo_layer_pop_female, population.id)
    if not by_sex and not layer_matches_job(
        widgets.combo_layer_pop_total, population.id
    ):
        raise LookupError(f"No population layer from job {population.id}")
    dlg.radio_population_baseline_bysex.setChecked(by_sex)
    dlg.radio_population_baseline_total.setChecked(not by_sex)


def verify_separate_input_paths(summary_job, productivity, land_cover, soc):
    """Ensure the submitted local calculation actually used the separate files."""
    from .harness import job_output_path

    periods = summary_job.params["periods"]
    if len(periods) != 1 or periods[0]["name"] != "baseline":
        raise AssertionError("Expected one baseline period in separate SDG calculation")
    params = periods[0]["params"]
    for key, source in (
        ("layer_traj_path", productivity),
        ("layer_perf_path", productivity),
        ("layer_state_path", productivity),
        ("layer_lc_path", land_cover),
        ("layer_soc_path", soc),
    ):
        expected = job_output_path(source)
        if expected is None or params.get(key) != str(expected):
            raise AssertionError(
                f"{key} did not use job {source.id}: {params.get(key)!r} != {expected}"
            )
