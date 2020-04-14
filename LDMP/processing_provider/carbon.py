import numpy as np

from osgeo import gdal, osr

from qgis import processing
from qgis.core import (QgsGeometry,
	               QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingException,
                       QgsProcessingParameterFile,
                       QgsProcessingParameterFileDestination,
                       QgsProcessingParameterNumber,
                       QgsProcessingOutputString,
                       QgsProcessingOutputNumber)
from qgis.PyQt.QtCore import QCoreApplication

from LDMP import log
from LDMP.summary import calc_cell_area

class TCSummary(QgsProcessingAlgorithm):
    """
    Used for summarizing results of output of the carbon change analysis.
    """

    def tr(self, string):
        return QCoreApplication.translate('processing\\carbon', string)

    def createInstance(self):
        # Must return a new copy of your algorithm.
        return TCSummary()

    def name(self):
        return 'carbon_summary'

    def displayName(self):
        return self.tr('Carbon change summary')

    def group(self):
        return self.tr('Carbon change')

    def groupId(self):
        return 'trendsearth'

    def shortHelpString(self):
        return self.tr('Summarize output of a carbon change analysis')

    def initAlgorithm(self, config=None):
        # Inputs
        self.addParameter(
            QgsProcessingParameterFile(
                'INPUT',
                self.tr('Input carbon analysis file')
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                'YEAR_START',
                self.tr('Starting year')
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                'YEAR_END',
                self.tr('Ending year')
            )
        )
        
        # Outputs
        self.addOutput(
            QgsProcessingOutputString(
                'FOREST_LOSS',
                self.tr('Forest loss per year in sq km.')
            )
        )
        self.addOutput(
            QgsProcessingOutputString(
                'CARBON_LOSS',
                self.tr('Carbon loss per year in tonnes of C')
            )
        )
        self.addOutput(
            QgsProcessingOutputNumber(
                'CARBON_INITIAL',
                self.tr('Initial tonnes of C')
            )
        )
        self.addOutput(
            QgsProcessingOutputNumber(
                'AREA_FOREST',
                self.tr('Area of forest in sq km')
            )
        )
        self.addOutput(
            QgsProcessingOutputNumber(
                'AREA_NON_FOREST',
                self.tr('Area of non-forest in sq km')
            )
        )
        self.addOutput(
            QgsProcessingOutputNumber(
                'AREA_MISSING',
                self.tr('Area of missing data in sq km')
            )
        )
        self.addOutput(
            QgsProcessingOutputNumber(
                'AREA_WATER',
                self.tr('Area of water in sq km')
            )
        )
        self.addOutput(
            QgsProcessingOutputNumber(
                'AREA_SITE',
                self.tr('Area of site in sq km')
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        src_file = self.parameterAsFile(parameters,'INPUT', context)
        year_start = self.parameterAsInt(parameters,'YEAR_START', context)
        year_end = self.parameterAsInt(parameters,'YEAR_END', context)

        src_ds = gdal.Open(src_file)

        band_f_loss = src_ds.GetRasterBand(1)
        band_tc = src_ds.GetRasterBand(2)

        block_sizes = band_f_loss.GetBlockSize()
        xsize = band_f_loss.XSize
        ysize = band_f_loss.YSize
        n_out_bands = 1

        x_block_size = block_sizes[0]
        y_block_size = block_sizes[1]

        src_gt = src_ds.GetGeoTransform()

        # Width of cells in longitude
        long_width = src_gt[1]
        # Set initial lat ot the top left corner latitude
        lat = src_gt[3]
        # Width of cells in latitude
        pixel_height = src_gt[5]

        area_missing = 0
        area_non_forest = 0
        area_water = 0
        area_site = 0
        initial_forest_area = 0
        initial_carbon_total = 0
        forest_loss = np.zeros(year_end - year_start)
        carbon_loss = np.zeros(year_end - year_start)

        blocks = 0
        for y in range(0, ysize, y_block_size):
            if y + y_block_size < ysize:
                rows = y_block_size
            else:
                rows = ysize - y
            for x in range(0, xsize, x_block_size):
                if feedback.isCanceled():
                    log("Processing of {} killed by user after processing {} out of {} blocks.".format(src_file, y, ysize))
                    break
                feedback.setProgress(100 * (float(y) + (float(x)/xsize)*y_block_size) / ysize)
                if x + x_block_size < xsize:
                    cols = x_block_size
                else:
                    cols = xsize - x

                f_loss_array = band_f_loss.ReadAsArray(x, y, cols, rows)
                tc_array = band_tc.ReadAsArray(x, y, cols, rows)

                # Caculate cell area for each horizontal line
                cell_areas = np.array([calc_cell_area(lat + pixel_height*n, lat + pixel_height*(n + 1), long_width) for n in range(rows)])
                cell_areas.shape = (cell_areas.size, 1)
                # Make an array of the same size as the input arrays containing 
                # the area of each cell (which is identicalfor all cells ina 
                # given row - cell areas only vary among rows)
                cell_areas_array = np.repeat(cell_areas, cols, axis=1)

                initial_forest_pixels = (f_loss_array == 0) | (f_loss_array > (year_start - 2000))
                # The site area includes everything that isn't masked
                area_missing = area_missing + np.sum(((f_loss_array == -32768) | (tc_array == -32768)) * cell_areas_array)
                area_water = area_water + np.sum((f_loss_array == -2) * cell_areas_array)
                area_non_forest = area_non_forest + np.sum((f_loss_array == -1) * cell_areas_array)
                area_site = area_site + np.sum((f_loss_array != -32767) * cell_areas_array)
                initial_forest_area = initial_forest_area + np.sum(initial_forest_pixels * cell_areas_array)
                initial_carbon_total = initial_carbon_total +  np.sum(initial_forest_pixels * tc_array * (tc_array >= 0) * cell_areas_array)

                for n in range(year_end - year_start):
                    # Note the codes are year - 2000
                    forest_loss[n] = forest_loss[n] + np.sum((f_loss_array == year_start - 2000 + n + 1) * cell_areas_array)
                    # Check units here - is tc_array in per m or per ha?
                    carbon_loss[n] = carbon_loss[n] + np.sum((f_loss_array == year_start - 2000 + n + 1) * tc_array * (tc_array >= 0) * cell_areas_array)

                blocks += 1
            lat += pixel_height * rows
        feedback.setProgress(100)

        if feedback.isCanceled():
            return {}
        else:
            # Convert all area tables from meters into hectares
            forest_loss = forest_loss * 1e-4
            # Note that carbon is scaled by 10
            carbon_loss = carbon_loss * 1e-4 / 10
            area_missing = area_missing * 1e-4
            area_water = area_water * 1e-4
            area_non_forest = area_non_forest * 1e-4
            area_site = area_site * 1e-4
            initial_forest_area = initial_forest_area * 1e-4
            # Note that carbon is scaled by 10
            initial_carbon_total = initial_carbon_total * 1e-4 / 10

        return {'FOREST_LOSS': np.array2string(forest_loss),
                'CARBON_LOSS': np.array2string(carbon_loss),
                'CARBON_INITIAL': initial_carbon_total,
                'AREA_FOREST': initial_forest_area, 
                'AREA_NON_FOREST': area_non_forest,
                'AREA_WATER': area_water, 
                'AREA_MISSING': area_missing,
                'AREA_SITE':  area_site}

