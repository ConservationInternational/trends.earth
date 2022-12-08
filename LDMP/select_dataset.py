import os
from pathlib import Path

from qgis.core import Qgis
from qgis.PyQt import QtCore
from qgis.PyQt import QtGui
from qgis.PyQt import QtWidgets
from qgis.PyQt import uic
from qgis.utils import iface

from .conf import OPTIONS_TITLE
from .conf import Setting
from .conf import settings_manager

Ui_DlgSelectDS, _ = uic.loadUiType(
    str(Path(__file__).parents[0] / "gui/DlgSelectDS.ui")
)

ICON_PATH = os.path.join(os.path.dirname(__file__), "icons")


class DlgSelectDataset(QtWidgets.QDialog, Ui_DlgSelectDS):
    changed_region: QtCore.pyqtSignal = QtCore.pyqtSignal()

    def __init__(self, parent=None, validate_all=False):
        super().__init__(parent)
        self.setupUi(self)

        self.validate_all = validate_all
        self.buttonBox.accepted.connect(self.on_accept)

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

    def update_current_region(self):
        region = settings_manager.get_value(Setting.AREA_NAME)
        self.region_la.setText(self.tr(f"Current region: {region}"))
        self.changed_region.emit()

    def run_settings(self):
        iface.showOptionsDialog(iface.mainWindow(), currentPage=OPTIONS_TITLE)
        self.update_current_region()

    def validate_selection(self) -> bool:
        # Validate user selection
        status = True

        self.msg_bar.clearWidgets()

        dataset_layer_refs = {
            'combo_dataset': self.tr('Dataset'),
            'combo_sdg': self.tr('SDG 15.3.1 Indicator'),
            'combo_prod': self.tr('Productivity Degradation'),
            'combo_lc': self.tr('Land Cover Degradation'),
            'combo_soil': self.tr('Soil Organic Carbon Degradation')
        }
        warning_msg = self.tr('No dataset or layer selected.')

        for combo_name, lbl in dataset_layer_refs.items():
            combo_widget = getattr(self, combo_name)

            try:
                no_ds_layer_msg = combo_widget.NO_DATASETS_MESSAGE
            except AttributeError:
                no_ds_layer_msg = combo_widget.NO_LAYERS_MESSAGE

            if combo_widget.currentText() == no_ds_layer_msg:
                self.msg_bar.pushMessage(
                    lbl,
                    warning_msg,
                    Qgis.MessageLevel.Warning,
                    4
                )
                if status:
                    status = False

        return status

    def on_accept(self):
        # Slot raised to check if all the datasets have been selected based
        # on the 'validate_all' flag.
        if self.validate_all:
            if not self.validate_selection():
                return

        self.accept()
