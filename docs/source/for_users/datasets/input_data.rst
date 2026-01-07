.. _input_data:

Input Data Used in Trends.Earth
=================================

|trends.earth| draws on a number of data sources. The data sets listed below are 
owned/made available by the following organizations and individuals under 
separate terms as indicated in their respective metadata.

NDVI
--------------------------------

+--------------------+-----------+---------+--------+------------------+
| Sensor/Dataset     | Temporal  | Spatial | Extent | License          |
+====================+===========+=========+========+==================+
| `AVHRR/GIMMS`_     | 1982-2015 | 8 km    | Global | `Public Domain`_ |
+--------------------+-----------+---------+--------+------------------+
| `MOD13Q1-coll6.1`_ | 2001-2024 | 250 m   | Global | `Public Domain`_ |
+--------------------+-----------+---------+--------+------------------+

.. _AVHRR/GIMMS: https://glam1.gsfc.nasa.gov
.. _MOD13Q1-coll6.1:
   https://www.earthdata.nasa.gov/data/catalog/lpcloud-mod13q1-061
.. _Public Domain: https://creativecommons.org/publicdomain/zero/1.0
.. _data:

Soil Moisture
--------------------------------

+----------------+-----------+---------------+--------+------------------+
| Sensor/Dataset | Temporal  | Spatial       | Extent | License          |
+================+===========+===============+========+==================+
| `MERRA 2`_     | 1980-2016 | 0.5° x 0.625° | Global | `Public Domain`_ |
+----------------+-----------+---------------+--------+------------------+
| `ERA I`_       | 1979-2016 | 0.75° x 0.75° | Global | `Public Domain`_ |
+----------------+-----------+---------------+--------+------------------+

.. _MERRA 2: https://gmao.gsfc.nasa.gov/reanalysis/MERRA-Land
.. _ERA I: 
   https://www.ecmwf.int/en/forecasts/datasets/reanalysis-datasets/era-interim-land

Precipitation and Drought
--------------------------------

+----------------------+-----------+-------------+---------+------------------+
| Sensor/Dataset       | Temporal  | Spatial     | Extent  | License          |
+======================+===========+=============+=========+==================+
| `GPCP v2.3 1 month`_ | 1979-2019 | 2.5° x 2.5° | Global  | `Public Domain`_ |
+----------------------+-----------+-------------+---------+------------------+
| `GPCC V6`_           | 1891-2019 | 1° x 1°     | Global  | `Public Domain`_ |
+----------------------+-----------+-------------+---------+------------------+
| `CHIRPS`_            | 1981-2024 | 5 km        | 50N-50S | `Public Domain`_ |
+----------------------+-----------+-------------+---------+------------------+
| `PERSIANN-CDR`_      | 1983-2024 | 25 km       | 60N-60S | `Public Domain`_ |
+----------------------+-----------+-------------+---------+------------------+

.. _GPCP v2.3 1 month: https://www.esrl.noaa.gov/psd/data/gridded/data.gpcp.html
.. _GPCC V6: https://www.esrl.noaa.gov/psd/data/gridded/data.gpcc.html
.. _CHIRPS:  https://www.chc.ucsb.edu/data/chirps
.. _PERSIANN-CDR: http://chrsdata.eng.uci.edu

Evapotranspiration
--------------------------------

+------------------+-----------+---------+--------+------------------+
| Sensor/Dataset   | Temporal  | Spatial | Extent | License          |
+==================+===========+=========+========+==================+
| MOD16A2GF_       | 2000-2014 | 1 km    | Global | `Public Domain`_ |
+------------------+-----------+---------+--------+------------------+

.. _MOD16A2GF:
   https://www.earthdata.nasa.gov/data/catalog/lpcloud-mod16a2gf-061

Land cover
--------------------------------

+-----------------------+-----------+---------+--------+-----------------+
| Sensor/Dataset        | Temporal  | Spatial | Extent | License         |
+=======================+===========+=========+========+=================+
| `ESA CCI Land Cover`_ | 1992-2022 | 300 m   | Global | `CC BY 4.0`_    |
+-----------------------+-----------+---------+--------+-----------------+

.. _ESA CCI Land Cover: https://cds.climate.copernicus.eu/datasets/satellite-land-cover?tab=overview
.. _CC BY 4.0: https://creativecommons.org/licenses/by/4.0/

Soil carbon
--------------------------------

+-----------------------+----------+---------+--------+-----------------+
| Sensor/Dataset        | Temporal | Spatial | Extent | License         |
+=======================+==========+=========+========+=================+
| `Soil Grids (ISRIC)`_ | Present  | 250 m   | Global | `CC by-SA 4.0`_ |
+-----------------------+----------+---------+--------+-----------------+

.. _Soil Grids (ISRIC): https://www.soilgrids.org/
.. _CC by-SA 4.0: https://creativecommons.org/licenses/by-sa/4.0

Agroecological Zones
--------------------------------

+---------------------------------------------------+----------+---------+--------+------------------+
| Sensor/Dataset                                    | Temporal | Spatial | Extent | License          |
+===================================================+==========+=========+========+==================+
| `FAO - IIASA Global Agroecological Zones (GAEZ)`_ | 2000     | 8 km    | Global | `Public Domain`_ |
+---------------------------------------------------+----------+---------+--------+------------------+

.. _FAO - IIASA Global Agroecological Zones (GAEZ): http://www.fao.org/nr/gaez/en

Administrative Boundaries
--------------------------------

+--------------------------------------------+----------+---------+--------+------------------+
| Sensor/Dataset                             | Temporal | Spatial | Extent | License          |
+============================================+==========+=========+========+==================+
| `geoBoundaries Administrative Boundaries`_ | Present  | 10/50m  | Global | `CC BY 4.0`_     |
+--------------------------------------------+----------+---------+--------+------------------+

.. note::
    The `geoBoundaries Administrative Boundaries`_ provided in Trends.Earth 
    are under the CC BY 4.0 license. The boundaries and names used, and the 
    designations used, in Trends.Earth do not imply official endorsement or 
    acceptance by Conservation International Foundation, or by its partner 
    organizations and contributors.

    If using Trends.Earth for official purposes, it is recommended that users 
    choose an official boundary provided by the designated office of their 
    country.

.. _geoBoundaries Administrative Boundaries: https://www.geoboundaries.org

Population
--------------------------------

+-------------------------------------------+-----------+---------+--------+--------------+
| Sensor/Dataset                            | Temporal  | Spatial | Extent | License      |
+===========================================+===========+=========+========+==============+
| `WorldPop`_ 100m Global Population grid   | 2000-2020 | 100m    | Global | `CC BY 4.0`_ |
+-------------------------------------------+-----------+---------+--------+--------------+

.. note::
    The `WorldPop`_ dataset included in Trends.Earth was produced by the
    `UNCCD`_ from publicly available data layers from the WorldPop project. This
    dataset is a combination of the national-level age and sex-disaggregated
    grids produced by the WorldPop project at 100m resolution. In support of
    UNCCD National Reporting on Strategic Objectives 2 and 3, UNCCD funded the
    development of a set of global mosaics, disaggregated by sex, giving
    population counts per pixel. These layers are used within Trends.Earth to
    tabulate population exposure to drought and degradation, disaggregated by
    sex.

    These data are also available in a publicly-accessible S3 bucket
    (trends.earth-shared, in the us-east-1 region), as tiled 32-bit floating
    point GeoTiffs at 100m, 300m, and 1200m resolution, at the following
    locations on s3:

    - s3://trends.earth-shared/worldpop/100m
    - s3://trends.earth-shared/worldpop/300m
    - s3://trends.earth-shared/worldpop/1200m

.. _UNCCD: https://www.unccd.int
.. _WorldPop: https://www.worldpop.org
