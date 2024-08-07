from dataclasses import dataclass

from qgis.core import QgsGeometry
from qgis.PyQt import QtCore, QtWidgets
from qgis.utils import iface

from .conf import OPTIONS_TITLE, AreaSetting, Setting, settings_manager
from .utils import FileUtils
from .visualization import get_admin_bbox


@dataclass(frozen=True)
class RegionInfo:
    """
    Contains region information including extents.
    """

    area_name: str
    geom: QgsGeometry
    country: str
    sub_national_name: str
    # Will only use city or region in the enum
    sub_national_type: AreaSetting


class RegionSelector(QtWidgets.QWidget):
    """
    Convenience widget for selecting a region in settings. Emits a
    'region_changed' signal containing details of the selected region.
    """

    region_changed = QtCore.pyqtSignal(RegionInfo)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lbl_region = QtWidgets.QLabel()

        self.btn_region_select = QtWidgets.QPushButton()
        self.btn_region_select.setText(self.tr("Change region"))
        self.btn_region_select.setIcon(FileUtils.get_icon("wrench.svg"))
        self.btn_region_select.clicked.connect(self.on_run_settings)

        self._layout = QtWidgets.QHBoxLayout()
        self._layout.addWidget(self.lbl_region)
        self._layout.addWidget(self.btn_region_select)
        self.setLayout(self._layout)

        self._current_region_name = None

        self._update_current_region()

    def _update_current_region(self):
        # Fetch and update the region in settings.
        region_info = self.region_info
        region_name = region_info.area_name

        self.lbl_region.setText(self.tr(f"Current region: {region_name}"))
        if not region_info.area_name:
            return

        # Emit signal only if region name has changed
        if self._current_region_name != region_name:
            self._current_region_name = region_name
            self.region_changed.emit(region_info)

    @property
    def region_info(self) -> RegionInfo:
        """
        Get current region details.
        """
        area_name = settings_manager.get_value(Setting.AREA_NAME)
        country = settings_manager.get_value(Setting.COUNTRY_NAME)
        admin_method = settings_manager.get_value(Setting.AREA_FROM_OPTION)
        if admin_method == "country_region":
            is_region = True
            admin_one_name = settings_manager.get_value(Setting.REGION_NAME)
            area_type = AreaSetting.COUNTRY_REGION
        else:
            is_region = False
            admin_one_name = settings_manager.get_value(Setting.CITY_NAME)
            area_type = AreaSetting.COUNTRY_CITY

        temp_admin_one_name = admin_one_name
        if admin_one_name == "All regions":
            temp_admin_one_name = None

        geom = get_admin_bbox(country, temp_admin_one_name, is_region)

        return RegionInfo(area_name, geom, country, admin_one_name, area_type)

    def on_run_settings(self):
        iface.showOptionsDialog(iface.mainWindow(), currentPage=OPTIONS_TITLE)
        self._update_current_region()

    def region_name(self) -> str:
        return self.lbl_region.text()
