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

from builtins import zip
from builtins import range
import os
import json
import tempfile

from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import QSettings

from osgeo import gdal, osr

from qgis.core import QgsGeometry
from qgis.utils import iface
mb = iface.messageBar()

from LDMP import log
from LDMP.api import run_script
from LDMP.calculate import DlgCalculateBase, get_script_slug, local_scripts
from LDMP.layers import create_local_json_metadata, add_layer
from LDMP.lc_setup import lc_setup_widget, lc_define_deg_widget
from LDMP.worker import AbstractWorker, StartWorker
from LDMP.gui.DlgCalculateLC import Ui_DlgCalculateLC

from LDMP.schemas.schemas import BandInfo, BandInfoSchema


class LandCoverChangeWorker(AbstractWorker):
    def __init__(self, in_f, out_f, trans_matrix, persistence_remap):
        AbstractWorker.__init__(self)
        self.in_f = in_f
        self.out_f = out_f
        self.trans_matrix = trans_matrix
        self.persistence_remap = persistence_remap

    def work(self):
        ds_in = gdal.Open(self.in_f)

        band_initial = ds_in.GetRasterBand(1)
        band_final = ds_in.GetRasterBand(2)

        block_sizes = band_initial.GetBlockSize()
        x_block_size = block_sizes[0]
        y_block_size = block_sizes[1]
        xsize = band_initial.XSize
        ysize = band_initial.YSize

        driver = gdal.GetDriverByName("GTiff")
        ds_out = driver.Create(self.out_f, xsize, ysize, 4, gdal.GDT_Int16, 
                               ['COMPRESS=LZW'])
        src_gt = ds_in.GetGeoTransform()
        ds_out.SetGeoTransform(src_gt)
        out_srs = osr.SpatialReference()
        out_srs.ImportFromWkt(ds_in.GetProjectionRef())
        ds_out.SetProjection(out_srs.ExportToWkt())

        blocks = 0
        for y in range(0, ysize, y_block_size):
            if y + y_block_size < ysize:
                rows = y_block_size
            else:
                rows = ysize - y
            for x in range(0, xsize, x_block_size):
                if self.killed:
                    log("Processing killed by user after processing {} out of {} blocks.".format(y, ysize))
                    break
                self.progress.emit(100 * (float(y) + (float(x)/xsize)*y_block_size) / ysize)
                if x + x_block_size < xsize:
                    cols = x_block_size
                else:
                    cols = xsize - x

                a_i = band_initial.ReadAsArray(x, y, cols, rows)
                a_f = band_final.ReadAsArray(x, y, cols, rows)

                a_tr = a_i*10 + a_f
                a_tr[(a_i < 1) | (a_f < 1)] <- -32768

                a_deg = a_tr.copy()
                for value, replacement in zip(self.trans_matrix[0], self.trans_matrix[1]):
                    a_deg[a_deg == int(value)] = int(replacement)
                
                # Recode transitions so that persistence classes are easier to 
                # map
                for value, replacement in zip(self.persistence_remap[0], self.persistence_remap[1]):
                    a_tr[a_tr == int(value)] = int(replacement)

                ds_out.GetRasterBand(1).WriteArray(a_deg, x, y)
                ds_out.GetRasterBand(2).WriteArray(a_i, x, y)
                ds_out.GetRasterBand(3).WriteArray(a_f, x, y)
                ds_out.GetRasterBand(4).WriteArray(a_tr, x, y)

                blocks += 1
        if self.killed:
            os.remove(out_file)
            return None
        else:
            return True

class DlgCalculateLC(DlgCalculateBase, Ui_DlgCalculateLC):
    def __init__(self, parent=None):
        super(DlgCalculateLC, self).__init__(parent)

        self.setupUi(self)

    def showEvent(self, event):
        super(DlgCalculateLC, self).showEvent(event)

        self.lc_setup_tab = lc_setup_widget
        self.TabBox.insertTab(0, self.lc_setup_tab, self.tr('Land Cover Setup'))

        self.lc_define_deg_tab = lc_define_deg_widget
        self.TabBox.insertTab(1, self.lc_define_deg_tab, self.tr('Define Degradation'))
        # These boxes may have been hidden if this widget was last shown on the 
        # SDG one step dialog
        self.lc_setup_tab.groupBox_esa_period.show()
        self.lc_setup_tab.use_custom.show()
        self.lc_setup_tab.groupBox_custom_bl.show()
        self.lc_setup_tab.groupBox_custom_tg.show()

        # This box may have been hidden if this widget was last shown on the 
        # SDG one step dialog
        self.lc_setup_tab.groupBox_esa_period.show()

        if self.reset_tab_on_showEvent:
            self.TabBox.setCurrentIndex(0)

        self.lc_setup_tab.use_custom_initial.populate()
        self.lc_setup_tab.use_custom_final.populate()

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super(DlgCalculateLC, self).btn_calculate()
        if not ret:
            return

        if self.lc_setup_tab.use_esa.isChecked():
            self.calculate_on_GEE()
        else:
            self.calculate_locally()

    def calculate_on_GEE(self):
        self.close()

        crosses_180th, geojsons = self.gee_bounding_box
        payload = {'year_baseline': self.lc_setup_tab.use_esa_bl_year.date().year(),
                   'year_target': self.lc_setup_tab.use_esa_tg_year.date().year(),
                   'geojsons': json.dumps(geojsons),
                   'crs': self.aoi.get_crs_dst_wkt(),
                   'crosses_180th': crosses_180th,
                   'trans_matrix': self.lc_define_deg_tab.trans_matrix_get(),
                   'remap_matrix': self.lc_setup_tab.dlg_esa_agg.get_agg_as_list(),
                   'task_name': self.options_tab.task_name.text(),
                   'task_notes': self.options_tab.task_notes.toPlainText()}

        resp = run_script(get_script_slug('land-cover'), payload)

        if resp:
            mb.pushMessage(self.tr("Submitted"),
                           self.tr("Land cover task submitted to Google Earth Engine."),
                           level=0, duration=5)
        else:
            mb.pushMessage(self.tr("Error"),
                           self.tr( "Unable to submit land cover task to Google Earth Engine."),
                           level=0, duration=5)

    def get_save_raster(self):
        raster_file, _ = QtWidgets.QFileDialog.getSaveFileName(self,
                                                        self.tr('Choose a name for the output file'),
                                                        QSettings().value("trends_earth/advanced/base_data_directory", None),
                                                        self.tr('Raster file (*.tif)'))
        if raster_file:
            if os.access(os.path.dirname(raster_file), os.W_OK):
                # QSettings().setValue("LDMP/output_dir", os.path.dirname(raster_file))
                return raster_file
            else:
                QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr(u"Cannot write to {}. Choose a different file.".format(raster_file)))
                return False

    def calculate_locally(self):
        trans_matrix = [[11, 12, 13, 14, 15, 16, 17,
                         21, 22, 23, 24, 25, 26, 27,
                         31, 32, 33, 34, 35, 36, 37,
                         41, 42, 43, 44, 45, 46, 47,
                         51, 52, 53, 54, 55, 56, 57,
                         61, 62, 63, 64, 65, 66, 67],
                        self.lc_define_deg_tab.trans_matrix_get()]

        # Remap the persistence classes so they are sequential, making them 
        # easier to assign a clear color ramp in QGIS
        persistence_remap = [[11, 12, 13, 14, 15, 16, 17,
                              21, 22, 23, 24, 25, 26, 27,
                              31, 32, 33, 34, 35, 36, 37,
                              41, 42, 43, 44, 45, 46, 47,
                              51, 52, 53, 54, 55, 56, 57,
                              61, 62, 63, 64, 65, 66, 67,
                              71, 72, 73, 74, 75, 76, 77],
                             [1, 12, 13, 14, 15, 16, 17,
                              21, 2, 23, 24, 25, 26, 27,
                              31, 32, 3, 34, 35, 36, 37,
                              41, 42, 43, 4, 45, 46, 47,
                              51, 52, 53, 54, 5, 56, 57,
                              61, 62, 63, 64, 65, 6, 67,
                              71, 72, 73, 74, 75, 76, 7]]

        if len(self.lc_setup_tab.use_custom_initial.layer_list) == 0:
            QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("You must add an initial land cover layer to your map before you can run the calculation."))
            return

        if len(self.lc_setup_tab.use_custom_final.layer_list) == 0:
            QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("You must add a final land cover layer to your map before you can run the calculation."))
            return

        # Select the initial and final bands from initial and final datasets 
        # (in case there is more than one lc band per dataset)
        lc_initial_vrt = self.lc_setup_tab.use_custom_initial.get_vrt()
        lc_final_vrt = self.lc_setup_tab.use_custom_final.get_vrt()

        year_baseline = self.lc_setup_tab.get_initial_year()
        year_target = self.lc_setup_tab.get_final_year()
        if int(year_baseline) >= int(year_target):
            QtWidgets.QMessageBox.information(None, self.tr("Warning"),
                self.tr('The initial year ({}) is greater than or equal to the target year ({}) - this analysis might generate strange results.'.format(year_baseline, year_target)))

        if self.aoi.calc_frac_overlap(QgsGeometry.fromRect(self.lc_setup_tab.use_custom_initial.get_layer().extent())) < .99:
            QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Area of interest is not entirely within the initial land cover layer."))
            return

        if self.aoi.calc_frac_overlap(QgsGeometry.fromRect(self.lc_setup_tab.use_custom_initial.get_layer().extent())) < .99:
            QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Area of interest is not entirely within the final land cover layer."))
            return

        out_f = self.get_save_raster()
        if not out_f:
            return

        self.close()

        # Add the lc layers to a VRT in case they don't match in resolution, 
        # and set proper output bounds
        in_vrt = tempfile.NamedTemporaryFile(suffix='.vrt').name
        gdal.BuildVRT(in_vrt,
                      [lc_initial_vrt, lc_final_vrt], 
                      resolution='highest', 
                      resampleAlg=gdal.GRA_NearestNeighbour,
                      outputBounds=self.aoi.get_aligned_output_bounds_deprecated(lc_initial_vrt),
                      separate=True)
        
        lc_change_worker = StartWorker(LandCoverChangeWorker,
                                       'calculating land cover change', in_vrt, 
                                       out_f, trans_matrix, persistence_remap)
        if not lc_change_worker.success:
            QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Error calculating land cover change."))
            return

        band_info = [BandInfo("Land cover (degradation)", add_to_map=True, metadata={'year_baseline': year_baseline, 'year_target': year_target}),
                     BandInfo("Land cover (7 class)", metadata={'year': year_baseline}),
                     BandInfo("Land cover (7 class)", metadata={'year': year_target}),
                     BandInfo("Land cover transitions", add_to_map=True, metadata={'year_baseline': year_baseline, 'year_target': year_target})]
        out_json = os.path.splitext(out_f)[0] + '.json'
        create_local_json_metadata(out_json, out_f, band_info, metadata={
                                                'task_name': self.options_tab.task_name.text(),
                                                'task_notes': self.options_tab.task_notes.toPlainText(),
                                                'source': local_scripts[self.get_subclass_name()]['source'],   # linked to calculate.local_script
                                                'id': self.output_tab.process_id,
                                                'start_date': self.output_tab.process_datetime_str})
        schema = BandInfoSchema()
        for band_number in range(len(band_info)):
            b = schema.dump(band_info[band_number])
            if b['add_to_map']:
                # The +1 is because band numbers start at 1, not zero
                add_layer(out_f, band_number + 1, b)
