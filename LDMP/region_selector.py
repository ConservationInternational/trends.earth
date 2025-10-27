from dataclasses import dataclass

from qgis.core import QgsGeometry
from qgis.PyQt import QtCore, QtWidgets
from qgis.utils import iface

from . import download
from .conf import OPTIONS_TITLE, TR_ALL_REGIONS, AreaSetting, Setting, settings_manager
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
        country_id = settings_manager.get_value(Setting.COUNTRY_ID)
        admin_method = settings_manager.get_value(Setting.AREA_FROM_OPTION)

        admin_bounds = download.get_admin_bounds()
        country_name = ""
        country_entry = None
        if country_id:
            for name, country in admin_bounds.items():
                if country.code == country_id:
                    country_name = name
                    country_entry = country
                    break

        is_region = admin_method == AreaSetting.COUNTRY_REGION.value
        area_type = (
            AreaSetting.COUNTRY_REGION if is_region else AreaSetting.COUNTRY_CITY
        )

        admin_one_name = ""
        admin_identifier = None

        if is_region:
            region_id = settings_manager.get_value(Setting.REGION_ID)
            if region_id:
                admin_identifier = str(region_id)
                if country_entry:
                    for name, rid in country_entry.level1_regions.items():
                        if rid == region_id:
                            admin_one_name = name
                            break
            else:
                admin_one_name = TR_ALL_REGIONS
        else:
            city_id = settings_manager.get_value(Setting.CITY_ID)
            if city_id and country_id:
                country_cities = download.get_cities().get(country_id, {})
                city = country_cities.get(str(city_id))
                if city:
                    admin_one_name = city.name_en
                    admin_identifier = str(city_id)

        geom = None
        if country_id:
            geom = get_admin_bbox(country_id, admin_identifier, is_region)

        return RegionInfo(area_name, geom, country_name, admin_one_name, area_type)

    def on_run_settings(self):
        iface.showOptionsDialog(iface.mainWindow(), currentPage=OPTIONS_TITLE)
        self._update_current_region()

    def region_name(self) -> str:
        return self.lbl_region.text()
