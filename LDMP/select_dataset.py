import os
from pathlib import Path

from qgis.PyQt import QtCore
from qgis.PyQt import QtGui
from qgis.PyQt import QtWidgets
from qgis.PyQt import uic

from .conf import Setting
from .conf import settings_manager
from .settings import DlgSettings

Ui_DlgSelectDS, _ = uic.loadUiType(
    str(Path(__file__).parents[0] / "gui/DlgSelectDS.ui")
)

ICON_PATH = os.path.join(os.path.dirname(__file__), "icons")


class DlgSelectDataset(QtWidgets.QDialog, Ui_DlgSelectDS):
    changed_region: QtCore.pyqtSignal = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self.update_current_region()
        self.region_button.setIcon(QtGui.QIcon(os.path.join(ICON_PATH, "wrench.svg")))
        self.region_button.clicked.connect(self.run_settings)
        self.changed_region.connect(self.populate_layers)

        self.combo_dataset.job_selected.connect(self.update_layers)
        self.populate_layers()
        self.combo_dataset.populate()

    def update_layers(self, job_id):
        self.combo_sdg.set_index_from_job_id(job_id)
        self.combo_prod.set_index_from_job_id(job_id)
        self.combo_lc.set_index_from_job_id(job_id)
        self.combo_soil.set_index_from_job_id(job_id)

    def populate_layers(self):
        self.combo_sdg.populate()
        self.combo_prod.populate()
        self.combo_lc.populate()
        self.combo_soil.populate()

    def accept(self):
        QtWidgets.QDialog.accept(self)

    def sdg_band(self):
        return self.combo_sdg.get_current_band()

    def prod_band(self):
        return self.combo_prod.get_current_band()

    def lc_band(self):
        return self.combo_lc.get_current_band()

    def soil_band(self):
        return self.combo_soil.get_current_band()

    def sdg_band(self):
        return self.combo_sdg.get_current_band()

    def update_current_region(self):
        region = settings_manager.get_value(Setting.AREA_NAME)
        self.region_la.setText(self.tr(f"Current region: {region}"))
        self.changed_region.emit()

    def run_settings(self):
        dlg_settings = DlgSettings(parent=self)

        if dlg_settings.exec_():
            self.update_current_region()
