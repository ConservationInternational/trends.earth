import os
import json

import numpy as np

from osgeo import gdal, osr

from qgis import processing
from qgis.core import (QgsGeometry,
	               QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingException,
                       QgsProcessingParameterFile,
                       QgsProcessingParameterString,
                       QgsProcessingParameterFileDestination,
                       QgsProcessingParameterNumber,
                       QgsProcessingOutputNumber)
from qgis.PyQt.QtCore import QCoreApplication

from LDMP import GetTempFilename, log


class ClipRaster(QgsProcessingAlgorithm):
    """
    Used for summarizing results of output of the carbon change analysis.
    """

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return ClipRaster()

    def name(self):
        return 'raster_clip'

    def displayName(self):
        return self.tr('Clip a raster')

    def group(self):
        return self.tr('Utilities')

    def groupId(self):
        return 'utilities'

    def shortHelpString(self):
        return self.tr('Clip a raster using a vector specified by a geojson')

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFile(
                'INPUT',
                self.tr('Input file')
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                'GEOJSON',
                self.tr('GeoJSON specifying area to clip to')
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                'OUTPUT_BOUNDS',
                self.tr('Output bounds (as a string readable by numpy.fromstring)')
            )
        )
        self.addParameter(
            QgsProcessingParameterFileDestination(
                'OUTPUT',
                self.tr('Output file')
            )
        )
        self.addOutput(
            QgsProcessingOutputNumber(
                'SUCCESS',
                self.tr('Did operation complete successfully?')
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        log('Starting algorithm')
        self.feedback = feedback # Needed for callback function
        log('1')
        in_file = self.parameterAsFile(parameters,'INPUT', context)
        log('2')
        out_file = self.parameterAsFile(parameters,'OUTPUT', context)
        log('3')
        output_bounds = np.fromstring(self.parameterAsString(parameters,'OUTPUT_BOUNDS', context), sep=',')
        log('4')
        log('GeoJSON: {}'.format(self.parameterAsString(parameters,'GEOJSON', context)))
        geojson = json.loads(self.parameterAsString(parameters,'GEOJSON', context))

        log('Dumping GeoJSON')
        json_file = GetTempFilename('.geojson')
        with open(json_file, 'w') as f:
            json.dump(geojson, f, separators=(',', ': '))

        log('Running GDAL')
        gdal.UseExceptions()
        res = gdal.Warp(out_file, in_file, format='GTiff',
                        cutlineDSName=json_file, srcNodata=-32768, 
                        outputBounds=output_bounds,
                        dstNodata=-32767,
                        dstSRS="epsg:4326",
                        outputType=gdal.GDT_Int16,
                        resampleAlg=gdal.GRA_NearestNeighbour,
                        creationOptions=['COMPRESS=LZW'],
                        callback=self.progress_callback)
        os.remove(json_file)

        log('Returning')
        if not res or self.feedback.isCanceled():
            return {'SUCCESS': False}
        else:
            return {'SUCCESS': True}


    def progress_callback(self, fraction, message, data):
        if self.feedback.isCanceled():
            return False
        else:
            self.feedback.setProgress(100 * fraction)
            return True


class GenerateMask(QgsProcessingAlgorithm):
    """
    Used to generate a raster that can be used as a mask.
    """

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return GenerateMask()

    def name(self):
        return 'generate_mask'

    def displayName(self):
        return self.tr('Generate mask')

    def group(self):
        return self.tr('Utilities')

    def groupId(self):
        return 'utilities'

    def shortHelpString(self):
        return self.tr('Generate a raster from a geojson for use as a mask')

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterString(
                'INPUT',
                self.tr('GeoJSON specifying mask')
            )
        )
        self.addParameter(
            QgsProcessingParameterFile(
                'MODEL_FILE',
                self.tr('Geotiff used as model for output bounds and resolution')
            )
        )
        self.addParameter(
            QgsProcessingParameterFileDestination(
                'OUTPUT',
                self.tr('Output geotiff file')
            )
        )
        self.addOutput(
            QgsProcessingOutputNumber(
                'SUCCESS',
                self.tr('Did operation complete successfully?')
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        self.feedback = feedback # Needed for callback function

        geojson = json.loads(self.parameterAsString(parameters,'INPUT', context))
        model_file = self.parameterAsFile(parameters,'MODEL_FILE', context)
        out_file = self.parameterAsFile(parameters,'OUTPUT', context)

        json_file = GetTempFilename('.geojson')
        with open(json_file, 'w') as f:
            json.dump(geojson, f, separators=(',', ': '))

        gdal.UseExceptions()

        # Assumes an image with no rotation
        gt = gdal.Info(model_file, format='json')['geoTransform']
        x_size, y_size= gdal.Info(model_file, format='json')['size']
        x_min = min(gt[0], gt[0] + x_size * gt[1])
        x_max = max(gt[0], gt[0] + x_size * gt[1])
        y_min = min(gt[3], gt[3] + y_size * gt[5])
        y_max = max(gt[3], gt[3] + y_size * gt[5])
        output_bounds = [x_min, y_min, x_max, y_max]
        x_res = gt[1]
        y_res = gt[5]

        res = gdal.Rasterize(out_file, json_file, format='GTiff',
                             outputBounds=output_bounds,
                             initValues=-32767, # Areas that are masked out
                             burnValues=1, # Areas that are NOT masked out
                             xRes=x_res,
                             yRes=y_res,
                             outputSRS="epsg:4326",
                             outputType=gdal.GDT_Int16,
                             creationOptions=['COMPRESS=LZW'],
                             callback=self.progress_callback)
        os.remove(json_file)

        if not res or self.feedback.isCanceled():
            return {'SUCCESS': False}
        else:
            return {'SUCCESS': True}


    def progress_callback(self, fraction, message, data):
        if self.feedback.isCanceled():
            return False
        else:
            self.feedback.setProgress(100 * fraction)
            return True
