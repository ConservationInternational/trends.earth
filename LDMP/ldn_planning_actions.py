"""Planning dataset summaries and actions shared with the planning panel."""

from pathlib import Path

from qgis.PyQt import QtCore, QtGui, QtWidgets
from te_schemas.jobs import JobStatus

from .jobs.manager import job_manager

PLANNING_INPUT_SCRIPT = "ldn-planning-input"
PLANNING_REPORT_SCRIPTS = {
    "ldn-planning-arr",
    "ldn-planning-hotspots",
    "ldn-planning-land-types",
    "ldn-planning-priority",
    "ldn-planning-selection",
    "ldn-planning-projection",
    "ldn-counterbalancing",
}
_AVAILABLE = (JobStatus.DOWNLOADED, JobStatus.GENERATED_LOCALLY)


def _script_name(job) -> str:
    script = getattr(job, "script", None)
    return getattr(script, "name", None) or getattr(script, "id", None) or ""


def planning_report(job) -> dict:
    job_manager.ensure_results_loaded(job)
    data = getattr(job.results, "data", None) or {}
    report = data.get("report")
    if not isinstance(report, dict):
        raise ValueError(  # noqa: TRY004
            "This dataset has no stored planning report. Rerun the analysis "
            "with the current plugin version to generate one."
        )
    return report


def report_files(job, suffix: str) -> list[Path]:
    job_path = job_manager.get_job_file_path(job)
    directory = job_path.parent
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.glob(f"*{suffix}") if path != job_path)


def open_file(path: Path) -> bool:
    return QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))


def open_report_folder(job):
    from . import openFolder

    openFolder(str(job_manager.get_job_file_path(job).parent))


def open_excel_report(job, parent=None):
    paths = report_files(job, ".xlsx")
    if not paths:
        QtWidgets.QMessageBox.information(
            parent,
            QtWidgets.QApplication.translate("ldn_planning", "No Excel report"),
            QtWidgets.QApplication.translate(
                "ldn_planning",
                "This dataset folder contains no Excel report. "
                "Rerun the analysis to generate one.",
            ),
        )
        return
    for path in paths:
        if not open_file(path):
            QtWidgets.QMessageBox.warning(
                parent,
                QtWidgets.QApplication.translate("ldn_planning", "Cannot open report"),
                str(path),
            )


class DlgPlanningSummary(QtWidgets.QDialog):
    def __init__(self, job, parent=None):
        super().__init__(parent)
        self.job = job
        self.setWindowTitle(
            self.tr("Planning summary — %s") % (job.task_name or str(job.id))
        )
        layout = QtWidgets.QVBoxLayout(self)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels([self.tr("Item"), self.tr("Value")])
        self.tree.setColumnWidth(0, 340)
        layout.addWidget(self.tree)
        note = QtWidgets.QLabel(
            self.tr(
                "Priority scores are relative preferences within one ARR class. "
                "Scenario figures are projected effects with upper-bound avoided "
                "losses — not observed gains or a like-for-like neutrality claim."
            )
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QtWidgets.QHBoxLayout()
        for label, callback in (
            (self.tr("Open Excel report"), lambda: open_excel_report(job, self)),
            (self.tr("Open report folder"), lambda: open_report_folder(job)),
        ):
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        buttons.addStretch()
        close = QtWidgets.QPushButton(self.tr("Close"))
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.resize(760, 560)
        try:
            report = planning_report(job)
        except ValueError as exc:
            self.tree.addTopLevelItem(
                QtWidgets.QTreeWidgetItem([self.tr("No report"), str(exc)])
            )
            return
        self._populate(self.tree.invisibleRootItem(), report)
        self.tree.expandToDepth(1)

    @staticmethod
    def _format(value) -> str:
        if isinstance(value, bool) or value is None:
            return str(value)
        if isinstance(value, float):
            return f"{value:,.4g}"
        return str(value)

    def _populate(self, parent_item, value):
        if isinstance(value, dict):
            items = value.items()
        elif isinstance(value, list):
            items = ((f"[{index}]", child) for index, child in enumerate(value, 1))
        else:
            return
        for key, child in items:
            if isinstance(child, (dict, list)):
                item = QtWidgets.QTreeWidgetItem([str(key), ""])
                parent_item.addChild(item)
                self._populate(item, child)
            else:
                parent_item.addChild(
                    QtWidgets.QTreeWidgetItem([str(key), self._format(child)])
                )


def show_planning_summary(job, parent=None):
    job_manager.ensure_results_loaded(job)
    DlgPlanningSummary(job, parent).exec()


def launch_calculate_dialog(
    main_dock, factory, draft_name=None, project_inputs=None, **preselect
):
    from .conf import KNOWN_SCRIPTS

    dialog_class, script_name = factory()
    options = {"draft_name": draft_name} if draft_name is not None else {}
    dialog = dialog_class(
        main_dock.iface, KNOWN_SCRIPTS[script_name], parent=main_dock, **options
    )
    for key, value in preselect.items():
        setattr(dialog, key, value)
    if project_inputs is not None:
        dialog.project_inputs = project_inputs
    main_dock.pause_scheduler()
    try:
        dialog.exec()
    finally:
        main_dock.resume_scheduler()


def select_job_band(widget, job_id, parent, label, band_index=None):
    for index, band in enumerate(widget.layer_list or []):
        if str(band.job.id) == str(job_id) and (
            band_index is None or band.band_index == band_index
        ):
            widget.comboBox_layers.setCurrentIndex(index)
            return
    widget.comboBox_layers.setCurrentIndex(-1)
    QtWidgets.QMessageBox.warning(
        parent,
        QtWidgets.QApplication.translate("ldn_planning", "Dataset unavailable"),
        QtWidgets.QApplication.translate(
            "ldn_planning",
            "The selected %s is unavailable for this area. Choose another dataset.",
        )
        % label,
    )


def validate_project_dialog(dialog):
    inputs = getattr(dialog, "project_inputs", None)
    if inputs is None:
        return
    from .ldn_planning_panel import current_area

    if (
        inputs["panel"].operation_context() != inputs["state"]
        or current_area()["sha256"] != inputs["state"]["area"]["sha256"]
    ):
        raise ValueError(
            dialog.tr(
                "Project inputs or region changed. Reopen the operation from LDN Planning."
            )
        )


def priority_factory():
    from .calculate_ldn_priority import DlgCalculateLDNPlanningPriority

    return DlgCalculateLDNPlanningPriority, "ldn-planning-priority"


def selection_factory():
    from .calculate_ldn_priority import DlgCalculateLDNPlanningSelection

    return DlgCalculateLDNPlanningSelection, "ldn-planning-selection"


def arr_factory():
    from .calculate_ldn_planning import DlgCalculateLDNPlanningARR

    return DlgCalculateLDNPlanningARR, "ldn-planning-arr"


def land_types_factory():
    from .calculate_ldn_planning import DlgCalculateLDNPlanningLandTypes

    return DlgCalculateLDNPlanningLandTypes, "ldn-planning-land-types"


def configure_scoring_profile(job, parent=None):
    from .ldn_planning_assets import DlgScoringProfile

    try:
        dialog = DlgScoringProfile(job, parent)
    except (OSError, ValueError) as exc:
        QtWidgets.QMessageBox.critical(
            parent,
            QtWidgets.QApplication.translate("ldn_planning", "Cannot use input"),
            str(exc),
        )
        return
    dialog.exec()


def attach_planning_actions(button, job, main_dock) -> bool:
    name = _script_name(job)
    is_input = name == PLANNING_INPUT_SCRIPT
    if not is_input and name not in PLANNING_REPORT_SCRIPTS:
        return False
    menu = QtWidgets.QMenu(button)

    def tr(text):
        return QtWidgets.QApplication.translate("ldn_planning", text)

    if is_input:
        menu.addAction(
            tr("Configure scoring profile..."),
            lambda: configure_scoring_profile(job, main_dock),
        )
        menu.addAction(
            tr("Use in prioritization..."),
            lambda: open_planning_panel(main_dock),
        )
    else:
        menu.addAction(
            tr("View planning summary..."),
            lambda: show_planning_summary(job, main_dock),
        )
        menu.addAction(
            tr("Open Excel report"), lambda: open_excel_report(job, main_dock)
        )
        menu.addAction(tr("Open report folder"), lambda: open_report_folder(job))
        if name == "ldn-planning-priority":
            menu.addAction(
                tr("Select candidate areas..."),
                lambda: use_in_project(main_dock, job, "priority"),
            )
        elif name == "ldn-planning-selection":
            menu.addAction(
                tr("Use in scenario..."),
                lambda: use_in_project(main_dock, job, "candidate"),
            )
    menu.addAction(
        tr("Open LDN Planning tab..."),
        lambda: open_planning_panel(main_dock),
    )
    button.setMenu(menu)
    button.setEnabled(job.status in _AVAILABLE)
    button.setToolTip(tr("LDN planning actions"))
    return True


def open_planning_panel(main_dock):
    from .ldn_planning_panel import open_panel

    return open_panel(main_dock)


def use_in_project(main_dock, job, key):
    panel = open_planning_panel(main_dock)
    projects = panel.data["projects"] if panel.data else []
    if not projects:
        QtWidgets.QMessageBox.information(
            panel,
            panel.tr("Planning project"),
            panel.tr("Create a project in LDN Planning first."),
        )
        return
    names = [p["name"] for p in projects]
    name, accepted = QtWidgets.QInputDialog.getItem(
        panel,
        panel.tr("Choose planning project"),
        panel.tr("Use dataset in project"),
        names,
        max(0, names.index(panel._project()["name"]) if panel._project() else 0),
        False,
    )
    if not accepted:
        return
    project = next(p for p in projects if p["name"] == name)
    if (
        QtWidgets.QMessageBox.question(
            panel,
            panel.tr("Change project selection"),
            panel.tr(
                "Use '%s' in '%s'? Existing results are unchanged; affected drafts need review."
            )
            % (job.task_name or str(job.id), name),
        )
        != QtWidgets.QMessageBox.StandardButton.Yes
    ):
        return
    panel.data["current"] = project["id"]
    project["selections"][key] = {
        "job_id": str(job.id),
        "area_sha256": project["area"]["sha256"],
    }
    panel._save()
    panel.refresh()
    panel._focus_section("targets" if key == "candidate" else "candidate")
