import os

import numpy as np
from osgeo import gdal

data_folder = 'D:/Documents and Settings/azvoleff/OneDrive - Conservation International Foundation/Data/Degradation_Paper/GEE_Rasters'


gdal.BuildVRT('baseline.tif', baseline_files, a_srs=crs('+init=epsg:4326'))

f_in = os.path.listdir(os.path.join(data_folder), pattern='ldn_baseline_2001_2015_250m_ha[-.0-9]*tif$')

next(x for x in all_arr if x[0] > 0)[1]
    ds_in = gdal.Open(self.in_f)
