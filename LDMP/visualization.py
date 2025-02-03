"""
/***************************************************************************
 LDMP - A QGIS plugin
 This plugin supports monitoring and reporting of land degradation to the UNCCD
 and in support of the SDG Land Degradation Neutrality (LDN) target.
                              -------------------
        begin                : 2017-05-23
        git sha              : $Format:%H$
        copyright            : (C) 2017 by Conservation International
        email                : trends.earth@conservation.org
 ***************************************************************************/
"""

import os
import typing
from pathlib import Path

from qgis import processing
from qgis.core import (
    QgsFeatureRequest,
    QgsGeometry,
    QgsLayerDefinition,
    QgsProject,
    QgsReadWriteContext,
    QgsRectangle,
    QgsVectorLayer,
)
from qgis.PyQt import QtWidgets, QtXml, uic
from qgis.utils import iface

from . import conf, download
from .logger import log
from .utils import FileUtils

DlgVisualizationBasemapUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgVisualizationBasemap.ui")
)
DlgVisualizationCreateMapUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgVisualizationCreateMap.ui")
)


def set_fill_style(maplayers, id, style="no"):
    # Function to set brush style for a map layer in an XML layer definition
    for n in range(maplayers.length()):
        m_l = maplayers.at(n)
        # Note that firstChild is needed as id is an element node,
        # so its text is stored in the first child of that node
        if m_l.namedItem("id").firstChild().nodeValue() == id:
            layer_props = (
                m_l.namedItem("renderer-v2")
                .namedItem("symbols")
                .namedItem("symbol")
                .namedItem("layer")
                .childNodes()
            )
            for m in range(layer_props.length()):
                elem = layer_props.at(m).toElement()
                if elem.attribute("k") == "style":
                    elem.setAttribute("v", style)


class zoom_to_admin_poly:
    def __init__(self, admin_code, admin_1=False):
        self.admin_code = admin_code
        if admin_1:
            self.lyr_source = os.path.normpath(
                os.path.join(
                    os.path.dirname(__file__),
                    "data",
                    "ne_10m_admin_1_states_provinces.shp",
                )
            )
            self.field = "adm1_code"
        else:
            self.lyr_source = os.path.normpath(
                os.path.join(
                    os.path.dirname(__file__), "data", "ne_10m_admin_0_countries.shp"
                )
            )
            self.field = "ISO_A3"

    def zoom(self):
        layer = None
        for lyr in QgsProject.instance().layerStore().mapLayers().values():
            if self.lyr_source in os.path.normpath(lyr.source()):
                layer = lyr
                break
        if not layer:
            raise LookupError(
                "Unable to locate layer for extent for admin code {}".format(
                    self.admin_code
                )
            )
        # Note that this layer will have the selected admin region filtered out, so
        # that data will not be masked in this area. So need to temporarily remove
        # this filter and then reapply it.
        subset_string = layer.subsetString()
        layer.setSubsetString("")
        feature = None
        for f in layer.getFeatures():
            if f.attribute(self.field) == self.admin_code:
                feature = f
                break
        if not feature:
            raise LookupError(
                "Unable to locate polygon for admin code {}".format(self.admin_code)
            )
        # TODO: Need to reproject the geometry to match the canvas CRS
        self.canvas = iface.mapCanvas()
        # Reapply the original feature filter on this layer
        layer.setSubsetString(subset_string)
        self.bbox = feature.geometry().boundingBox()
        log("Bounding box for zoom is: {}".format(self.bbox.toString()))
        self.canvas.setExtent(self.bbox)
        self.canvas.refresh()


def country_name_from_code(code: str) -> str:
    """
    Returns the country name from the corresponding ISO code.
    """
    countries = list(conf.ADMIN_BOUNDS_KEY.values())
    cnts = [cnt for cnt in countries if cnt.code == code]
    if len(cnts) == 0:
        return ""

    return cnts[0].name


def admin_one_name_from_code(country_name: str, sub_code: str) -> str:
    """
    Returns the sub-national name given the country name and
    sub-national code.
    """
    country = conf.ADMIN_BOUNDS_KEY.get(country_name, None)
    if country is None:
        return ""

    admin_one_name = ""
    for name, code in country.level1_regions.items():
        if code == sub_code:
            admin_one_name = name
            break

    return admin_one_name


def get_admin_bbox(
    country_name: str, admin_one: str = None, is_admin_one_region: bool = True
) -> QgsGeometry:
    """
    Returns the geometry of the given country or sub-national city or region
    else None if not found or if there is an issue in reading the relevant
    data source layer(s).
    If 'admin_one' is a region then 'is_admin_one_region' should be True
    (default) else if it is a city then 'is_admin_one_region' should be False.
    """
    if not os.path.exists(country_data_path()):
        return None

    # Get the country code as defined in 'download.get_admin_bounds()'. We
    # need this since some country names are partially abbreviated and in
    # such a case, it will not be possible to locate them in the national
    # data shapefile.
    admin_bounds = download.get_admin_bounds()
    country_info = admin_bounds.get(country_name, None)
    if not country_info:
        return None

    country_code = country_info.code

    # Country-level bounds
    if not admin_one:
        nl = QgsVectorLayer(country_data_path())
        if not nl.isValid():
            return None

        feat_request = QgsFeatureRequest()
        feat_exp = f"\"ISO_A3\"='{country_code}'"
        feat_request.setFilterExpression(feat_exp)
        feat_iter = nl.getFeatures(feat_request)
        feat = next(feat_iter, None)
        if feat is None:
            return None

        return feat.geometry()

    else:
        snl = QgsVectorLayer(sub_national_data_path())
        if not snl.isValid():
            return None

        # Attribute name to get matching feature in admin1 layer
        admin_one_attr = ""
        admin_one_attr_val = ""

        # City-level - get region from populated places layer
        if not is_admin_one_region:
            country_cities = download.get_cities().get(country_name, None)
            if country_cities is None:
                return None

            # Get wof_id corresponding to the given city name
            wof_ids = [
                ci.wof_id for ci in country_cities.values() if ci.name_en == admin_one
            ]
            if len(wof_ids) == 0:
                return None

            # Get 'adm1name' from wof_id in populated places layer
            wof_id = wof_ids[0]
            pl = QgsVectorLayer(places_data_path())
            if not pl.isValid():
                return None

            feat_request = QgsFeatureRequest()
            feat_exp = f"\"wof_id\"='{wof_id}'"
            feat_request.setFilterExpression(feat_exp)
            feat_iter = pl.getFeatures(feat_request)
            feat = next(feat_iter, None)
            if feat is None:
                return None

            admin_one_attr_val = feat["ADM1NAME"]
            admin_one_attr = "name"

        # Region-level
        else:
            # Use region code to retrieve feature
            admin_one_attr_val = country_info.level1_regions.get(admin_one, None)
            admin_one_attr = "adm1_code"

        feat_request = QgsFeatureRequest()
        feat_exp = f"\"{admin_one_attr}\"='{admin_one_attr_val}'"
        feat_request.setFilterExpression(feat_exp)
        feat_iter = snl.getFeatures(feat_request)
        feat = next(feat_iter, None)
        if feat is None:
            return None

        return feat.geometry()


def country_data_path() -> str:
    """
    Returns the path for the vector file containing country data.
    """
    return f"{FileUtils.plugin_dir()}/data/ne_10m_admin_0_countries.shp"


def sub_national_data_path() -> str:
    """
    Returns the path for the vector file containing sub-national data.
    """
    root_dir = FileUtils.plugin_dir()
    return f"{root_dir}/data/ne_10m_admin_1_states_provinces.shp"


def places_data_path() -> str:
    """
    Returns the path for the vector file containing data on populated places.
    """
    root_dir = FileUtils.plugin_dir()
    return f"{root_dir}/data/ne_10m_populated_places.shp"


class ExtractAdministrativeArea:
    """
    Uses a heuristic approach to try get the country name (and possibly
    region) that intersect with the input extents.
    """

    EXTRACT_BY_LOC_ALG = "native:extractbylocation"
    EXTENT_TO_LAYER_ALG = "native:extenttolayer"

    def __init__(self, extent: QgsRectangle):
        self._extent = extent
        self._national_data_path = country_data_path()
        self._sub_national_data_path = sub_national_data_path()
        self._extent_layer = None
        self._national_layer = None
        self._sub_nat_layer = None

        self._create_layers()

    @classmethod
    def extents_to_str(cls, ext: QgsRectangle) -> str:
        """
        Formats the extents to a string representation that can be used in
        a processing algorithm.
        """
        return (
            f"{ext.xMinimum()!s},{ext.xMaximum()!s},{ext.yMinimum()!s},"
            f"{ext.yMaximum()!s} [EPSG:4326]"
        )

    def _create_layers(self):
        # Create reference layers for analysis.
        # Extent to layer
        ext_str = self.extents_to_str(self._extent)
        ext_params = {"INPUT": ext_str, "OUTPUT": "TEMPORARY_OUTPUT"}
        ext_output = processing.run(self.EXTENT_TO_LAYER_ALG, ext_params)
        self._extent_layer = ext_output["OUTPUT"]
        self._national_layer = QgsVectorLayer(self._national_data_path)
        self._sub_nat_layer = QgsVectorLayer(self._sub_national_data_path)

    @property
    def extent(self) -> QgsRectangle:
        """
        Returns the extents used to determine the administrative area.
        """
        return self._extent

    def get_admin_area(self) -> typing.Tuple[str, str]:
        """
        Returns the matching country name and sub-region name, or 'All
        regions' if extent covers the whole country.
        """
        cnt_name, region = "", ""

        # Field names
        cnt_code_attr = "ISO_A3"

        # Check layers
        if (
            not self._extent_layer.isValid()
            or not self._national_layer.isValid()
            or not self._sub_nat_layer.isValid()
        ):
            return "", ""

        # Start with national
        nat_ext_layer = self._extract_by_loc(self._national_layer)
        if nat_ext_layer.isValid():
            feat_cnt = nat_ext_layer.featureCount()
            if feat_cnt == 1:
                feat = next(nat_ext_layer.getFeatures())

            elif feat_cnt > 1:
                # Get country with the largest area as it will be the one
                # covering our area of interest.
                feats_iter = nat_ext_layer.getFeatures()
                feat = max(feats_iter, key=lambda f: f.geometry().area())

            if feat_cnt > 0:
                cnt_name = country_name_from_code(feat[cnt_code_attr])

        if cnt_name:
            region = conf.TR_ALL_REGIONS
        else:
            # Try sub-national starting with the WITHIN predicate
            cnt_name, region = self._admin_from_sub_national_extraction_op([6])
            if not cnt_name or not region:
                # Use INTERSECT predicate
                cnt_name, region = self._admin_from_sub_national_extraction_op([0])

        return cnt_name, region

    def _admin_from_sub_national_extraction_op(
        self, predicates
    ) -> typing.Tuple[str, str]:
        """
        Returns the country name and level admin name by intersecting with
        the sub-national layer using the given predicates.
        """
        cnt_name, region = "", ""

        # Field names
        sub_cnt_attr = "adm0_a3"
        sub_admin_one_attr = "adm1_code"

        sub_nat_ext_layer = self._extract_by_loc(self._sub_nat_layer, predicates)
        if sub_nat_ext_layer.isValid():
            feat_count = sub_nat_ext_layer.featureCount()
            if feat_count == 1:
                feat = next(sub_nat_ext_layer.getFeatures())
                cnt_name = country_name_from_code(feat[sub_cnt_attr])
                sub_code = feat[sub_admin_one_attr]
                region = admin_one_name_from_code(cnt_name, sub_code)
                if not region:
                    region = conf.TR_ALL_REGIONS

            elif feat_count > 1:
                # Just return the national name and 'All regions'
                feat = next(sub_nat_ext_layer.getFeatures())
                cnt_name = country_name_from_code(feat[sub_cnt_attr])
                region = conf.TR_ALL_REGIONS

        return cnt_name, region

    def _extract_by_loc(self, input_layer, predicates=None) -> QgsVectorLayer:
        # Extract by location processing algorithm
        if predicates is None:
            predicates = [6]

        extract_params = {
            "INPUT": input_layer,
            "PREDICATE": predicates,
            "INTERSECT": self._extent_layer,
            "OUTPUT": "TEMPORARY_OUTPUT",
        }
        proc_output = processing.run(self.EXTRACT_BY_LOC_ALG, extract_params)

        return proc_output["OUTPUT"]


class DlgVisualizationBasemap(QtWidgets.QDialog, DlgVisualizationBasemapUi):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        if not conf.ADMIN_BOUNDS_KEY:
            raise Exception("Admin boundaries not available")
        self.area_admin_0.addItems(sorted(conf.ADMIN_BOUNDS_KEY.keys()))
        self.populate_admin_1()

        self.area_admin_0.currentIndexChanged.connect(self.populate_admin_1)

        self.buttonBox.accepted.connect(self.ok_clicked)
        self.buttonBox.rejected.connect(self.cancel_clicked)

        self.checkBox_mask.stateChanged.connect(self.checkBox_mask_statechanged)

    def checkBox_mask_statechanged(self):
        if self.checkBox_mask.isChecked():
            self.label_maskselect.setEnabled(True)
            self.label_admin0.setEnabled(True)
            self.label_admin1.setEnabled(True)
            self.area_admin_0.setEnabled(True)
            self.area_admin_1.setEnabled(True)
        else:
            self.label_maskselect.setEnabled(False)
            self.label_admin0.setEnabled(False)
            self.label_admin1.setEnabled(False)
            self.area_admin_0.setEnabled(False)
            self.area_admin_1.setEnabled(False)

    def populate_admin_1(self):
        self.area_admin_1.clear()
        self.area_admin_1.addItems([conf.TR_ALL_REGIONS])
        current_country_name = self.area_admin_0.currentText()
        country = conf.ADMIN_BOUNDS_KEY[current_country_name]
        admin1_regions = sorted(country.level1_regions.keys())
        self.area_admin_1.addItems(admin1_regions)

    def ok_clicked(self):
        self.close()

        zoomer = None
        use_mask = self.checkBox_mask.isChecked()
        country_name = self.area_admin_0.currentText()
        admin_level_one = None
        if self.area_admin_1.currentText():
            admin_level_one = self.area_admin_1.currentText()

        # Download basemap and get layer definition object
        status, document = download_base_map(use_mask, country_name, admin_level_one)
        if status:
            if use_mask:
                current_country = conf.ADMIN_BOUNDS_KEY[country_name]
                if admin_level_one is None or admin_level_one == conf.TR_ALL_REGIONS:
                    admin_code = current_country.code
                    zoomer = zoom_to_admin_poly(admin_code)
                else:
                    admin_code = current_country.level1_regions[admin_level_one]
                    zoomer = zoom_to_admin_poly(admin_code, True)

            # Always add the basemap at the top of the TOC
            root = QgsProject.instance().layerTreeRoot().insertGroup(0, "Basemap")
            QgsLayerDefinition.loadLayerDefinition(
                document, QgsProject.instance(), root, QgsReadWriteContext()
            )

            if zoomer:
                zoomer.zoom()
        else:
            QtWidgets.QMessageBox.critical(
                self, self.tr("Error"), self.tr("Error downloading basemap data.")
            )

    def cancel_clicked(self):
        self.close()


def download_base_map(
    use_mask=True, country_name=None, admin_level_one=None
) -> typing.Tuple[bool, QtXml.QDomDocument]:
    # Download basemap and return layer definition
    if admin_level_one is None:
        admin_level_one = conf.TR_ALL_REGIONS

    document = None

    ret = download.extract_zipfile("trends.earth_basemap_data.zip", verify=False)

    if ret:
        f = open(os.path.join(os.path.dirname(__file__), "data", "basemap.qlr"))
        lyr_def_content = f.read()
        f.close()

        # The basemap data, when downloaded, is stored in the data
        # subfolder of the plugin directory
        lyr_def_content = lyr_def_content.replace(
            "DATA_FOLDER", os.path.join(os.path.dirname(__file__), "data")
        )

        if use_mask:
            current_country = conf.ADMIN_BOUNDS_KEY[country_name]
            if admin_level_one == conf.TR_ALL_REGIONS:
                # Mask out a level 0 admin area - this is default, so don't
                # need to edit the brrush styles
                admin_code = current_country.code
                lyr_def_content = lyr_def_content.replace(
                    "MASK_SQL_ADMIN0",
                    "|subset=&quot;ISO_A3&quot; != '{}'".format(admin_code),
                )
                lyr_def_content = lyr_def_content.replace("MASK_SQL_ADMIN1", "")
                document = QtXml.QDomDocument()
                document.setContent(lyr_def_content)
            else:
                # Mask out a level 1 admin area
                current_region_name = admin_level_one
                admin_code = current_country.level1_regions[current_region_name]
                lyr_def_content = lyr_def_content.replace("MASK_SQL_ADMIN0", "")
                lyr_def_content = lyr_def_content.replace(
                    "MASK_SQL_ADMIN1",
                    "|subset=&quot;adm1_code&quot; != '{}'".format(admin_code),
                )

                # Set national borders to no brush, and regional borders to
                # solid brush
                document = QtXml.QDomDocument()
                document.setContent(lyr_def_content)
                maplayers = document.elementsByTagName("maplayer")
                set_fill_style(maplayers, "ne_10m_admin_0_countries", "no")
                set_fill_style(maplayers, "ne_10m_admin_1_states_provinces", "solid")
        else:
            # Don't mask any areas
            lyr_def_content = lyr_def_content.replace("MASK_SQL_ADMIN0", "")
            lyr_def_content = lyr_def_content.replace("MASK_SQL_ADMIN1", "")

            # To not use a mask, need to set the fill style to no brush
            document = QtXml.QDomDocument()
            document.setContent(lyr_def_content)
            maplayers = document.elementsByTagName("maplayer")
            set_fill_style(maplayers, "ne_10m_admin_0_countries", "no")

    return ret, document


class DlgVisualizationCreateMap(QtWidgets.QDialog, DlgVisualizationCreateMapUi):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setupUi(self)

        # TODO: Remove the combo boxes, etc.for now...
        self.combo_layers.hide()
        self.layer_combo_label.hide()

        self.buttonBox.accepted.connect(self.ok_clicked)
        self.buttonBox.rejected.connect(self.cancel_clicked)

    def cancel_clicked(self):
        self.close()

    def ok_clicked(self):
        if self.portrait_layout.isChecked():
            orientation = "portrait"
        else:
            orientation = "landscape"

        self.close()

        template = os.path.join(
            os.path.dirname(__file__), "data", "map_template_{}.qpt".format(orientation)
        )

        with open(template) as f:
            new_composer_content = f.read()
        document = QtXml.QDomDocument()
        document.setContent(new_composer_content)

        if self.title.text():
            title = self.title.text()
        else:
            title = "trends.earth map"
        comp_window = iface.createNewComposer(title)
        composition = comp_window.composition()
        composition.loadFromTemplate(document)

        canvas = iface.mapCanvas()
        map_item = composition.getComposerItemById("te_map")
        map_item.setMapCanvas(canvas)
        map_item.zoomToExtent(canvas.extent())

        map_item.renderModeUpdateCachedImage()

        datasets = composition.getComposerItemById("te_datasets")
        datasets.setText(
            'Created using <a href="http://trends.earth">trends.earth</a>. Projection: decimal degrees, WGS84. Datasets derived from {{COMING SOON}}.'
        )
        datasets.setHtmlState(True)
        author = composition.getComposerItemById("te_authors")
        author.setText(self.authors.text())
        logo = composition.getComposerItemById("te_logo")
        logo_path = os.path.join(
            os.path.dirname(__file__), "data", "trends_earth_logo_bl_600width.png"
        )
        logo.setPicturePath(logo_path)
        legend = composition.getComposerItemById("te_legend")
        legend.setAutoUpdateModel(True)
