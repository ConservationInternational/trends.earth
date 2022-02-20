# -*- coding: utf-8 -*-
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
from pathlib import Path
import typing

from qgis.PyQt import (
    QtWidgets,
    QtXml,
    uic
)

from qgis.core import (
    QgsLayerDefinition,
    QgsProject,
    QgsReadWriteContext,
)
from qgis.utils import iface

from . import (
    conf,
    download,
)
from .logger import log

DlgVisualizationBasemapUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgVisualizationBasemap.ui"))
DlgVisualizationCreateMapUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgVisualizationCreateMap.ui"))


def set_fill_style(maplayers, id, style='no'):
    # Function to set brush style for a map layer in an XML layer definition
    for n in range(maplayers.length()):
        m_l = maplayers.at(n)
        # Note that firstChild is needed as id is an element node,
        # so its text is stored in the first child of that node
        if m_l.namedItem('id').firstChild().nodeValue() == id:
            layer_props = m_l.namedItem('renderer-v2').namedItem('symbols').namedItem('symbol').namedItem('layer').childNodes()
            for m in range(layer_props.length()):
                elem = layer_props.at(m).toElement()
                if elem.attribute('k') == 'style':
                    elem.setAttribute('v', style)


class zoom_to_admin_poly(object):
    def __init__(self, admin_code, admin_1=False):
        self.admin_code = admin_code
        if admin_1:
            self.lyr_source = os.path.normpath(os.path.join(os.path.dirname(__file__), 'data', 'ne_10m_admin_1_states_provinces.shp'))
            self.field = 'adm1_code'
        else:
            self.lyr_source = os.path.normpath(os.path.join(os.path.dirname(__file__), 'data', 'ne_10m_admin_0_countries.shp'))
            self.field = 'ISO_A3'

    def zoom(self):
        layer = None
        for lyr in QgsProject.instance().layerStore().mapLayers().values():
            if self.lyr_source in os.path.normpath(lyr.source()):
                layer = lyr
                break
        if not layer:
            raise LookupError('Unable to locate layer for extent for admin code {}'.format(self.admin_code))
        # Note that this layer will have the selected admin region filtered out, so
        # that data will not be masked in this area. So need to temporarily remove
        # this filter and then reapply it.
        subset_string = layer.subsetString()
        layer.setSubsetString('')
        feature = None
        for f in layer.getFeatures():
            if f.attribute(self.field) == self.admin_code:
                feature = f
                break
        if not feature:
            raise LookupError('Unable to locate polygon for admin code {}'.format(self.admin_code))
        # TODO: Need to reproject the geometry to match the canvas CRS
        self.canvas = iface.mapCanvas()
        # Reapply the original feature filter on this layer
        layer.setSubsetString(subset_string)
        self.bbox = feature.geometry().boundingBox()
        log('Bounding box for zoom is: {}'.format(self.bbox.toString()))
        self.canvas.setExtent(self.bbox)
        self.canvas.refresh()


class DlgVisualizationBasemap(QtWidgets.QDialog, DlgVisualizationBasemapUi):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        if not conf.ADMIN_BOUNDS_KEY:
            raise Exception('Admin boundaries not available')
        self.area_admin_0.addItems(
            sorted(conf.ADMIN_BOUNDS_KEY.keys())
        )
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
        self.area_admin_1.addItems(['All regions'])
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
        status, document = download_base_map(country_name, use_mask, admin_level_one)
        if status:
            if use_mask:
                current_country = conf.ADMIN_BOUNDS_KEY[country_name]
                if admin_level_one is None or admin_level_one == 'All regions':
                    admin_code = current_country.code
                    zoomer = zoom_to_admin_poly(admin_code)
                else:
                    admin_code = current_country.level1_regions[admin_level_one]
                    zoomer = zoom_to_admin_poly(admin_code, True)

            # Always add the basemap at the top of the TOC
            root = QgsProject.instance().layerTreeRoot().insertGroup(0, 'Basemap')
            QgsLayerDefinition.loadLayerDefinition(
                document,
                QgsProject.instance(),
                root,
                QgsReadWriteContext()
            )

            if zoomer:
                zoomer.zoom()
        else:
            QtWidgets.QMessageBox.critical(
                self,
                self.tr("Error"),
                self.tr("Error downloading basemap data.")
            )

    def cancel_clicked(self):
        self.close()


def download_base_map(
        use_mask=True,
        country_name=None,
        admin_level_one=None
) -> typing.Tuple[bool, QtXml.QDomDocument]:
    # Download basemap and return layer definition
    if admin_level_one is None:
        admin_level_one = 'All regions'

    document = None

    ret = download.extract_zipfile('trends.earth_basemap_data.zip', verify=False)

    if ret:
        f = open(os.path.join(os.path.dirname(__file__), 'data', 'basemap.qlr'), 'rt')
        lyr_def_content = f.read()
        f.close()

        # The basemap data, when downloaded, is stored in the data
        # subfolder of the plugin directory
        lyr_def_content = lyr_def_content.replace('DATA_FOLDER', os.path.join(os.path.dirname(__file__), 'data'))

        if use_mask:
            current_country = conf.ADMIN_BOUNDS_KEY[country_name]
            if admin_level_one == 'All regions':
                # Mask out a level 0 admin area - this is default, so don't
                # need to edit the brrush styles
                admin_code = current_country.code
                lyr_def_content = lyr_def_content.replace('MASK_SQL_ADMIN0',
                                                          "|subset=&quot;ISO_A3&quot; != '{}'".format(admin_code))
                lyr_def_content = lyr_def_content.replace('MASK_SQL_ADMIN1', '')
                document = QtXml.QDomDocument()
                document.setContent(lyr_def_content)
            else:
                # Mask out a level 1 admin area
                current_region_name = admin_level_one
                admin_code = current_country.level1_regions[current_region_name]
                lyr_def_content = lyr_def_content.replace('MASK_SQL_ADMIN0', '')
                lyr_def_content = lyr_def_content.replace('MASK_SQL_ADMIN1',
                                                          "|subset=&quot;adm1_code&quot; != '{}'".format(admin_code))

                # Set national borders to no brush, and regional borders to
                # solid brush
                document = QtXml.QDomDocument()
                document.setContent(lyr_def_content)
                maplayers = document.elementsByTagName('maplayer')
                set_fill_style(maplayers, 'ne_10m_admin_0_countries', 'no')
                set_fill_style(maplayers, 'ne_10m_admin_1_states_provinces', 'solid')
        else:
            # Don't mask any areas
            lyr_def_content = lyr_def_content.replace('MASK_SQL_ADMIN0', '')
            lyr_def_content = lyr_def_content.replace('MASK_SQL_ADMIN1', '')

            # To not use a mask, need to set the fill style to no brush
            document = QtXml.QDomDocument()
            document.setContent(lyr_def_content)
            maplayers = document.elementsByTagName('maplayer')
            set_fill_style(maplayers, 'ne_10m_admin_0_countries', 'no')

    return ret, document


class DlgVisualizationCreateMap(QtWidgets.QDialog, DlgVisualizationCreateMapUi):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setupUi(self)

        #TODO: Remove the combo boxes, etc.for now...
        self.combo_layers.hide()
        self.layer_combo_label.hide()

        self.buttonBox.accepted.connect(self.ok_clicked)
        self.buttonBox.rejected.connect(self.cancel_clicked)

    def cancel_clicked(self):
        self.close()

    def ok_clicked(self):
        if self.portrait_layout.isChecked():
            orientation = 'portrait'
        else:
            orientation = 'landscape'

        self.close()

        template = os.path.join(os.path.dirname(__file__), 'data',
                                'map_template_{}.qpt'.format(orientation))

        with open(template, 'rt') as f:
            new_composer_content = f.read()
        document = QtXml.QDomDocument()
        document.setContent(new_composer_content)

        if self.title.text():
            title = self.title.text()
        else:
            title = 'trends.earth map'
        comp_window = iface.createNewComposer(title)
        composition = comp_window.composition()
        composition.loadFromTemplate(document)

        canvas = iface.mapCanvas()
        map_item = composition.getComposerItemById('te_map')
        map_item.setMapCanvas(canvas)
        map_item.zoomToExtent(canvas.extent())

        map_item.renderModeUpdateCachedImage()

        datasets = composition.getComposerItemById('te_datasets')
        datasets.setText('Created using <a href="http://trends.earth">trends.earth</a>. Projection: decimal degrees, WGS84. Datasets derived from {{COMING SOON}}.')
        datasets.setHtmlState(True)
        author = composition.getComposerItemById('te_authors')
        author.setText(self.authors.text())
        logo = composition.getComposerItemById('te_logo')
        logo_path = os.path.join(os.path.dirname(__file__), 'data', 'trends_earth_logo_bl_600width.png')
        logo.setPicturePath(logo_path)
        legend = composition.getComposerItemById('te_legend')
        legend.setAutoUpdateModel(True)
