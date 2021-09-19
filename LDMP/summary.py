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

from . import conf
from .logger import log

import numpy as np

#  Calculate the area of a slice of the globe from the equator to the parallel
#  at latitude f (on WGS84 ellipsoid). Based on:
# https://gis.stackexchange.com/questions/127165/more-accurate-way-to-calculate-area-of-rasters
def _slice_area(f):
    a = 6378137 # in meters
    b = 6356752.3142 # in meters,
    e = np.sqrt(1 - np.square(b / a))
    zp = 1 + e * np.sin(f)
    zm = 1 - e * np.sin(f)
    return np.pi * np.square(b) * ((2 * np.arctanh(e * np.sin(f))) / (2 * e) + np.sin(f) / (zp * zm))


# Formula to calculate area of a raster cell, following
# https://gis.stackexchange.com/questions/127165/more-accurate-way-to-calculate-area-of-rasters
def calc_cell_area(ymin, ymax, x_width):
    'Calculate cell area on WGS84 ellipsoid'
    if ymin > ymax:
        temp = ymax
        ymax = ymin
        ymin = temp
    # ymin: minimum latitude
    # ymax: maximum latitude
    # x_width: width of cell in degrees
    return (_slice_area(np.deg2rad(ymax)) - _slice_area(np.deg2rad(ymin))) * (x_width / 360.)


def write_row_to_sheet(sheet, d, row, first_col):
    for col in range(d.size):
        cell = sheet.cell(row=row, column=col + first_col)
        cell.value = d[col]


def write_col_to_sheet(sheet, d, col, first_row):
    for row in range(d.size):
        cell = sheet.cell(row=row + first_row, column=col)
        cell.value = d[row]


def write_table_to_sheet(sheet, d, first_row, first_col):
    for row in range(d.shape[0]):
        for col in range(d.shape[1]):
            cell = sheet.cell(row=row + first_row, column=col + first_col)
            cell.value = d[row, col]


# Used for reading arrays returned as text from algorithms implemented through 
# QgsProcessing
def np_array_from_str(s, dtype=float, count=-1, sep=' '):
    s = s.strip('[')
    s = s.strip(']')
    return np.fromstring(s, dtype=dtype, count=count, sep=sep)
