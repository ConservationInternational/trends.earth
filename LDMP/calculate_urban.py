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

import tempfile

import openpyxl
from openpyxl.drawing.image import Image
from osgeo import gdal, osr

import qgis.gui
from qgis.core import QgsGeometry
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import QSettings, QDate, QCoreApplication

from .algorithms import models
from .calculate import (
    DlgCalculateBase,
    ClipWorker,
    json_geom_to_geojson,
)
from .gui.DlgCalculateUrbanData import Ui_DlgCalculateUrbanData
from .gui.DlgCalculateUrbanSummaryTable import Ui_DlgCalculateUrbanSummaryTable
from .jobs.manager import job_manager
from .layers import get_band_infos, create_local_json_metadata, add_layer
from .worker import AbstractWorker, StartWorker
from .schemas.schemas import BandInfo, BandInfoSchema
from .summary import *


class tr_calculate_urban(object):
    def tr(message):
        return QCoreApplication.translate("tr_calculate_urban", message)


class UrbanSummaryWorker(AbstractWorker):
    def __init__(self, src_file, urban_band_nums, pop_band_nums, n_classes):
        AbstractWorker.__init__(self)

        self.src_file = src_file
        self.urban_band_nums = [int(x) for x in urban_band_nums]
        self.pop_band_nums = [int(x) for x in pop_band_nums]
        self.n_classes = n_classes

    def work(self):
        self.toggle_show_progress.emit(True)
        self.toggle_show_cancel.emit(True)

        src_ds = gdal.Open(self.src_file)

        urban_bands = [src_ds.GetRasterBand(b) for b in self.urban_band_nums]
        pop_bands = [src_ds.GetRasterBand(b) for b in self.pop_band_nums]

        block_sizes = urban_bands[1].GetBlockSize()
        xsize = urban_bands[1].XSize
        ysize = urban_bands[1].YSize

        x_block_size = block_sizes[0]
        y_block_size = block_sizes[1]

        src_gt = src_ds.GetGeoTransform()

        # Width of cells in longitude
        long_width = src_gt[1]
        # Set initial lat ot the top left corner latitude
        lat = src_gt[3]
        # Width of cells in latitude
        pixel_height = src_gt[5]

        areas = np.zeros((self.n_classes, len(self.urban_band_nums)))
        populations = np.zeros((self.n_classes, len(self.pop_band_nums)))

        blocks = 0
        for y in range(0, ysize, y_block_size):
            if y + y_block_size < ysize:
                rows = y_block_size
            else:
                rows = ysize - y
            for x in range(0, xsize, x_block_size):
                if self.killed:
                    log("Processing of {} killed by user after processing {} out of {} blocks.".format(self.prod_out_file, y, ysize))
                    break
                self.progress.emit(100 * (float(y) + (float(x)/xsize)*y_block_size) / ysize)
                if x + x_block_size < xsize:
                    cols = x_block_size
                else:
                    cols = xsize - x

                # Caculate cell area for each horizontal line
                cell_areas = np.array([calc_cell_area(lat + pixel_height*n, lat + pixel_height*(n + 1), long_width) for n in range(rows)])
                # Convert areas from meters into hectares
                cell_areas = cell_areas * 1e-4
                cell_areas.shape = (cell_areas.size, 1)
                # Make an array of the same size as the input arrays containing 
                # the area of each cell (which is identicalfor all cells ina 
                # given row - cell areas only vary among rows)
                cell_areas_array = np.repeat(cell_areas, cols, axis=1)

                # Loop over the bands (years)
                for i in range(len(self.urban_band_nums)):
                    urban_array = urban_bands[i].ReadAsArray(x, y, cols, rows)
                    pop_array = pop_bands[i].ReadAsArray(x, y, cols, rows)
                    pop_array[pop_array == -32768] = 0
                    # Now loop over the classes
                    for c in range(1, self.n_classes + 1):
                        areas[c - 1, i] += np.sum((urban_array == c) * cell_areas_array)
                        pop_masked = pop_array.copy() * (urban_array == c)
                        # Convert population densities to persons per hectare 
                        # from persons per sq km
                        pop_masked = pop_masked / 100
                        populations[c - 1, i] += np.sum(pop_masked * cell_areas_array)

                blocks += 1
            lat += pixel_height * rows
        self.progress.emit(100)

        if self.killed:
            return None
        else:
            return list((areas, populations))


class DlgCalculateUrbanData(DlgCalculateBase, Ui_DlgCalculateUrbanData):

    def __init__(
            self,
            iface: qgis.gui.QgisInterface,
            script: models.ExecutionScript,
            parent: QtWidgets.QWidget = None,
    ):
        super().__init__(iface, script, parent)
        self.setupUi(self)
        self.urban_thresholds_updated()

        self.spinBox_pct_urban.valueChanged.connect(self.urban_thresholds_updated)
        self.spinBox_pct_suburban.valueChanged.connect(self.urban_thresholds_updated)
        self.initiliaze_settings()

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super(DlgCalculateUrbanData, self).btn_calculate()
        if not ret:
            return

        # Limit area that can be processed
        aoi_area = self.aoi.get_area() / (1000 * 1000)
        log(u'AOI area is: {:n}'.format(aoi_area))
        if aoi_area > 25000:
            QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                    self.tr("The bounding box of the requested area (approximately {:.6n} sq km) is too large. The urban area change tool can process a maximum area of 25,000 sq. km at a time. Choose a smaller area to process.".format(aoi_area)))
            return False

        self.calculate_on_GEE()

    def urban_thresholds_updated(self):
        self.spinBox_pct_suburban.setRange(0, self.spinBox_pct_urban.value() - 1)
        self.spinBox_pct_urban.setRange(self.spinBox_pct_suburban.value() + 1, 100)

    def get_pop_def_is_un(self):
        if self.pop_adjusted.isChecked():
            return True
        elif self.pop_unadjusted.isChecked():
            return False
        else:
            # Should never get here
            raise

    def calculate_on_GEE(self):
        self.close()

        crosses_180th, geojsons = self.gee_bounding_box

        payload = {
            'un_adju': self.get_pop_def_is_un(),
            'isi_thr': self.spinBox_isi_thr.value(),
            'ntl_thr': self.spinBox_ntl_thr.value(),
            'wat_thr': self.spinBox_wat_thr.value(),
            'cap_ope': self.spinBox_cap_ope.value(),
            'pct_suburban': self.spinBox_pct_suburban.value()/100.,
            'pct_urban': self.spinBox_pct_urban.value()/100.,
            'geojsons': json.dumps(geojsons),
            'crs': self.aoi.get_crs_dst_wkt(),
            'crosses_180th': crosses_180th,
            'task_name': self.execution_name_le.text(),
            'task_notes': self.options_tab.task_notes.toPlainText()
        }

        resp = job_manager.submit_remote_job(payload, self.script.id)

        if resp:
            main_msg = "Submitted"
            description = (
                "Urban area change calculation submitted to Google Earth Engine.")

        else:
            main_msg = "Error"
            description = "Unable to submit urban area task Google Earth Engine."
        self.mb.pushMessage(
            self.tr(main_msg),
            self.tr(description),
            level=0,
            duration=5
        )


class DlgCalculateUrbanSummaryTable(DlgCalculateBase, Ui_DlgCalculateUrbanSummaryTable):
    def __init__(self, parent=None):
        super(DlgCalculateUrbanSummaryTable, self).__init__(parent)

        self.setupUi(self)

        self.add_output_tab(['.xlsx', '.json', '.tif'])
        self.initiliaze_settings()

    def showEvent(self, event):
        super(DlgCalculateUrbanSummaryTable, self).showEvent(event)

        self.combo_layer_urban_series.populate()

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super(DlgCalculateUrbanSummaryTable, self).btn_calculate()
        if not ret:
            return

        ######################################################################
        # Check that all needed input layers are selected
        if len(self.combo_layer_urban_series.layer_list) == 0:
            QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("You must add an urban series layer to your map before you can use the urban change summary tool."))
            return

        #######################################################################
        # Check that the layers cover the full extent needed
        if self.aoi.calc_frac_overlap(QgsGeometry.fromRect(self.combo_layer_urban_series.get_layer().extent())) < .99:
            QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Area of interest is not entirely within the urban series layer."))
            return

        self.close()

        #######################################################################
        # Load all datasets to VRTs (to select only the needed bands)
        band_infos = get_band_infos(self.combo_layer_urban_series.get_data_file())

        urban_annual_band_indices = [i for i, bi in enumerate(band_infos) if bi['name'] == 'Urban']
        urban_annual_band_indices.sort(key=lambda i: band_infos[i]['metadata']['year'])
        urban_years = [bi['metadata']['year'] for bi in band_infos if bi['name'] == 'Urban']
        urban_files = []
        for i in urban_annual_band_indices:
            f = tempfile.NamedTemporaryFile(suffix='.vrt').name
            # Add once since band numbers don't start at zero
            gdal.BuildVRT(f,
                          self.combo_layer_urban_series.get_data_file(),
                          bandList=[i + 1])
            urban_files.append(f)


        pop_annual_band_indices = [i for i, bi in enumerate(band_infos) if bi['name'] == 'Population']
        pop_annual_band_indices.sort(key=lambda i: band_infos[i]['metadata']['year'])
        pop_years = [bi['metadata']['year'] for bi in band_infos if bi['name'] == 'Population']
        pop_files = []
        for i in pop_annual_band_indices:
            f = tempfile.NamedTemporaryFile(suffix='.vrt').name
            # Add once since band numbers don't start at zero
            gdal.BuildVRT(f,
                          self.combo_layer_urban_series.get_data_file(),
                          bandList=[i + 1])
            pop_files.append(f)

        assert (len(pop_files) == len(urban_files))
        assert (urban_years == pop_years)

        in_files = list(urban_files)
        in_files.extend(pop_files)
        urban_band_nums = np.arange(len(urban_files)) + 1
        pop_band_nums = np.arange(len(pop_files)) + 1 + urban_band_nums.max()

        # Remember the first value is an indication of whether dataset is 
        # wrapped across 180th meridian
        wkts = self.aoi.meridian_split('layer', 'wkt', warn=False)[1]
        bbs = self.aoi.get_aligned_output_bounds(urban_files[1])

        ######################################################################
        # Process the wkts using a summary worker
        output_indicator_tifs = []
        output_indicator_json = self.output_tab.output_basename.text() + '.json'
        for n in range(len(wkts)):
            # Compute the pixel-aligned bounding box (slightly larger than 
            # aoi). Use this instead of croptocutline in gdal.Warp in order to 
            # keep the pixels aligned with the chosen productivity layer.
        
            # Combines SDG 15.3.1 input raster into a VRT and crop to the AOI
            indic_vrt = tempfile.NamedTemporaryFile(suffix='.vrt').name
            log(u'Saving indicator VRT to: {}'.format(indic_vrt))
            # The plus one is because band numbers start at 1, not zero
            gdal.BuildVRT(indic_vrt,
                          in_files,
                          outputBounds=bbs[n],
                          resolution='highest',
                          resampleAlg=gdal.GRA_NearestNeighbour,
                          separate=True)

            if len(wkts) > 1:
                output_indicator_tif = os.path.splitext(output_indicator_json)[0] + '_{}.tif'.format(n)
            else:
                output_indicator_tif = os.path.splitext(output_indicator_json)[0] + '.tif'
            output_indicator_tifs.append(output_indicator_tif)

            log(u'Saving urban clipped files to {}'.format(output_indicator_tif))
            geojson = json_geom_to_geojson(QgsGeometry.fromWkt(wkts[n]).asJson())
            clip_worker = StartWorker(ClipWorker, 'masking layers (part {} of {})'.format(n + 1, len(wkts)), 
                                      indic_vrt, output_indicator_tif,
                                      geojson, bbs[n])
            if not clip_worker.success:
                QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("Error masking urban change input layers."))
                return

            ######################################################################
            #  Calculate urban change table
            log('Calculating summary table...')
            urban_summary_worker = StartWorker(UrbanSummaryWorker,
                                               'calculating summary table (part {} of {})'.format(n + 1, len(wkts)),
                                               output_indicator_tif,
                                               urban_band_nums, pop_band_nums, 9)
            if not urban_summary_worker.success:
                QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("Error calculating urban change summary table."))
                return
            else:
                if n == 0:
                     areas, \
                             populations = urban_summary_worker.get_return()
                else:
                     these_areas, \
                             these_populations = urban_summary_worker.get_return()
                     areas = areas + these_areas
                     populations = populations + these_populations

        make_summary_table(areas, populations, 
                self.output_tab.output_basename.text() + '.xlsx')

        # Add the indicator layers to the map
        output_indicator_bandinfos = [BandInfo("Urban", add_to_map=True, metadata={'year': 2000}),
                                      BandInfo("Urban", add_to_map=True, metadata={'year': 2005}),
                                      BandInfo("Urban", add_to_map=True, metadata={'year': 2010}),
                                      BandInfo("Urban", add_to_map=True, metadata={'year': 2015}),
                                      BandInfo("Population", metadata={'year': 2000}),
                                      BandInfo("Population", metadata={'year': 2005}),
                                      BandInfo("Population", metadata={'year': 2010}),
                                      BandInfo("Population", metadata={'year': 2015})]
        if len(output_indicator_tifs) == 1:
            output_file = output_indicator_tifs[0]
        else:
            output_file = os.path.splitext(output_indicator_json)[0] + '.vrt'
            gdal.BuildVRT(output_file, output_indicator_tifs)

        # set alg metadata
        metadata = self.setMetadata()
        metadata['params'] = {}
        metadata['params']['layer_urban_series'] = self.combo_layer_urban_series.get_data_file()
        metadata['params']['crs'] = self.aoi.get_crs_dst_wkt()
        crosses_180th, geojsons = self.gee_bounding_box
        metadata['params']['geojsons'] = json.dumps(geojsons)
        metadata['params']['crosses_180th'] = crosses_180th

        create_local_json_metadata(output_indicator_json, output_file, 
                output_indicator_bandinfos, metadata=metadata)
        schema = BandInfoSchema()
        add_layer(output_file, 1, schema.dump(output_indicator_bandinfos[0]))
        add_layer(output_file, 2, schema.dump(output_indicator_bandinfos[1]))
        add_layer(output_file, 3, schema.dump(output_indicator_bandinfos[2]))
        add_layer(output_file, 4, schema.dump(output_indicator_bandinfos[3]))

        return True


def make_summary_table(areas, populations, out_file):
    wb = openpyxl.load_workbook(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'data', 'summary_table_urban.xlsx'))

    ##########################################################################
    # SDG table
    ws_summary = wb['SDG 11.3.1 Summary Table']
    write_table_to_sheet(ws_summary, areas, 23, 2)
    write_table_to_sheet(ws_summary, populations, 37, 2)

    try:
        ws_summary_logo = Image(os.path.join(os.path.dirname(__file__), 'data', 'trends_earth_logo_bl_300width.png'))
        ws_summary.add_image(ws_summary_logo, 'E1')
    except ImportError:
        # add_image will fail on computers without PIL installed (this will be 
        # an issue on some Macs, likely others). it is only used here to add 
        # our logo, so no big deal.
        log('Adding Trends.Earth logo to worksheet FAILED')
        pass

    try:
        wb.save(out_file)
        log(u'Summary table saved to {}'.format(out_file))
        # QtWidgets.QMessageBox.information(None, tr_calculate_urban.tr("Success"),
        #                               tr_calculate_urban.tr(u'Summary table saved to {}'.format(out_file)))

    except IOError:
        log(u'Error saving {}'.format(out_file))
        QtWidgets.QMessageBox.critical(None, tr_calculate_urban.tr("Error"),
                                   tr_calculate_urban.tr(u"Error saving output table - check that {} is accessible and not already open.".format(out_file)))
