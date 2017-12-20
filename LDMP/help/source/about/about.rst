About
=====

|trends.earth| was produced as part of the project "Enabling the use of global 
data sources to assess and monitor land degradation at multiple scales", funded 
by the Global Environment Facility.

Contacting the team
-------------------

Contact the `trends.earth <mailto:trends.earth@conservation.org>`_ team with 
any comments or suggestions. If you have specific bugs to report or 
improvements to the tool that you would like to suggest, you can also submit 
them in the `issue tracker on Github 
<https://github.com/ConservationInternational/trends.earth/issues>`_ for 
|trends.earth|.

Authors
-------

Contributors to the documentation and |trends.earth| include Yengoh Genesis 
[1]_, Mariano Gonzalez-Roglich [2]_, Monica Noon [2]_, Lennart Olsson [1]_, 
Tristan Schnader [2]_, Anna Tengberg [1]_, and Alex Zvoleff [2]_.

The Land Degradation Monitoring Project is a partnership of Conservation 
International, Lund University, and the National Aeronautics and Space 
Administration (NASA), and is funded by the Global Environment Facility (GEF).

.. |logoCI| image:: /static/common/logo_CI_square.png
    :width: 150
    :target: http://www.conservation.org
.. |logoLund| image:: /static/common/logo_Lund_square.png
    :width: 125
    :target: http://www.lunduniversity.lu.se
.. |logoNASA| image:: /static/common/logo_NASA_square.png
    :width: 125
    :target: http://www.nasa.gov
.. |logoGEF| image:: /static/common/logo_GEF.png
    :width: 125
    :target: https://www.thegef.org

.. table::
    :align: center
    :widths: grid

    ======== ========== ========== =========
    |logoCI| |logoLund| |logoNASA| |logoGEF|
    ======== ========== ========== =========

.. [1] `Lund University <http://www.lunduniversity.lu.se>`_
.. [2] `Conservation International <http://www.conservation.org>`_

|trends.earth| uses `Google Earth Engine <https://earthengine.google.com>`_ to 
compute indicators in the cloud.

.. image:: /static/common/logo_earth_engine.png
    :align: center
    :width: 250
    :target: https://earthengine.google.com

Acknowledgements
----------------

The feedback provided by early users of |trends.earth| and by the participants 
in the webinars and workshops held by the GEF Land Degradation Monitoring 
Project have been critical to the development of the tool.

Neil Sims, Sasha Alexander, Renato Cumani, and Sara Minelli provided input on 
the implementation of the SDG 15.3 and LDN indicators in |trends.earth|, on the 
structure of the tool, and on the UNCCD reporting process, and also provided 
early input and testing of the tool.

The project acknowledges the participants of the workshop held in Morogoro, 
Tanzania in October, 2017 for sharing their feedback and suggestions on the 
tool: Jones Agwata, Col. Papa Assane Ndiour, Lt. Fendama Baldé, Papa Nékhou 
Diagne, Abdoul Aziz Diouf, Richard Alphonce Giliba, Moses Isabirye, Vettes 
Kalema, Joseph Kihaule, Prof. D.N. Kimaro, James Lwasa, Paulo Mandela, Modou 
Moustapha Sarr, Joseph Mutyaba, Stephen Muwaya, Joseph Mwalugelo, Prof. 
Majaliwa Mwanjalolo, Edson Aspon Mwijage, Jerome Nchimbi, Elibariki Ngowi, 
Tabby Njunge, Daniel Nkondola, Blaise Okinyi, Joseph Opio, Rozalia Rwegasira, 
Ndeye Kany Sarr, Mamadou Adama Sarr, Edward Senyonjo, Olipa Simon, Samba Sow, 
Felly Mugizi Tusiime and John Wasige.


Data sources
------------

|trends.earth| draws on a number of data sources. The data sets listed below are 
owned/made available by the following organizations and individuals under 
separate terms as indicated in their respective metadata.

NDVI
~~~~

+------------------+-----------+---------+--------+---------------------+
| Sensor/Dataset   | Temporal  | Spatial | Extent |       License       |
+==================+===========+=========+========+=====================+
| `AVHRR/GIMMS`_   | 1982-2015 | 8 km    | Global |  `Public Domain`_   |
+------------------+-----------+---------+--------+---------------------+
| `MOD13Q1-coll6`_ | 2001-2016 | 250 m   | Global |  `Public Domain`_   |
+------------------+-----------+---------+--------+---------------------+

.. _AVHRR/GIMMS: https://glam1.gsfc.nasa.gov/
.. _Public Domain: https://creativecommons.org/publicdomain/zero/1.0/",
.. _MOD13Q1-coll6:
   https://lpdaac.usgs.gov/dataset_discovery/modis/modis_products_table/mod13q1_v006
.. _Public Domain: https://creativecommons.org/publicdomain/zero/1.0/"
   
Soil moisture
~~~~~~~~~~~~~

+----------------+-----------+---------------+--------+---------------------+
| Sensor/Dataset | Temporal  | Spatial       | Extent |       License       |
+================+===========+===============+========+=====================+
| `MERRA 2`_     | 1980-2016 | 0.5° x 0.625° | Global |  `Public Domain`_   |
+----------------+-----------+---------------+--------+---------------------+
| `ERA I`_       | 1979-2016 | 0.75° x 0.75° | Global |  `Public Domain`_   |
+----------------+-----------+---------------+--------+---------------------+

.. _MERRA 2: https://gmao.gsfc.nasa.gov/reanalysis/MERRA-Land
.. _Public Domain: https://creativecommons.org/publicdomain/zero/1.0/"
.. _ERA I: 
   https://www.ecmwf.int/en/forecasts/datasets/reanalysis-datasets/era-interim-land
.. _Public Domain: https://creativecommons.org/publicdomain/zero/1.0/"

Precipitation
~~~~~~~~~~~~~

+----------------------+-----------+-------------+---------+---------------------+
| Sensor/Dataset       | Temporal  | Spatial     | Extent  |       License       |
+======================+===========+=============+=========+=====================+
| `GPCP v2.3 1 month`_ | 1979-2016 | 2.5° x 2.5° | Global  |  `Public Domain`_   |
+----------------------+-----------+-------------+---------+---------------------+
| `GPCC V7`_           | 1901-2016 | 1° x 1°     | Global  |  `Public Domain`_   |
+----------------------+-----------+-------------+---------+---------------------+
| `CHIRPS`_            | 1981-2016 | 5 km        | 50N-50S |  `Public Domain`_   |
+----------------------+-----------+-------------+---------+---------------------+
| `PERSIANN-CDR`_      | 1983-2015 | 25 km       | 60N-60S |  `Public Domain`_   |
+----------------------+-----------+-------------+---------+---------------------+

.. _GPCP v2.3 1 month: https://www.esrl.noaa.gov/psd/data/gridded/data.gpcp.html
.. _Public Domain: https://creativecommons.org/publicdomain/zero/1.0/"
.. _GPCC V7: https://www.esrl.noaa.gov/psd/data/gridded/data.gpcc.html
.. _Public Domain: https://creativecommons.org/publicdomain/zero/1.0/"
.. _CHIRPS:  http://chg.geog.ucsb.edu/data/chirps
.. _Public Domain: https://creativecommons.org/publicdomain/zero/1.0/"
.. _PERSIANN-CDR: http://chrsdata.eng.uci.edu
.. _Public Domain: https://creativecommons.org/publicdomain/zero/1.0/"

Evapotranspiration
~~~~~~~~~~~~~~~~~~

+----------------+-----------+---------+--------+---------------------+
| Sensor/Dataset | Temporal  | Spatial | Extent |       License       |
+================+===========+=========+========+=====================+
| MOD16A2_       | 2000-2014 | 1 km    | Global |  `Public Domain`_   |
+----------------+-----------+---------+--------+---------------------+

.. _MOD16A2:
   https://lpdaac.usgs.gov/dataset_discovery/modis/modis_products_table/mod16a2_v006
.. _Public Domain: https://creativecommons.org/publicdomain/zero/1.0/"

Land cover
~~~~~~~~~~

+-----------------------+-----------+---------+--------+------------------+
| Sensor/Dataset        | Temporal  | Spatial | Extent |     License      |
+=======================+===========+=========+========+==================+
| `ESA CCI Land Cover`_ | 1992-2015 | 300 m   | Global | `CC by-SA 3.0`_  |
+-----------------------+-----------+---------+--------+------------------+

.. _ESA CCI Land Cover: https://www.esa-landcover-cci.org/
.. _CC by-SA 3.0: https://creativecommons.org/licenses/by-sa/3.0/igo/",

Soil carbon
~~~~~~~~~~~

+-----------------------+----------+---------+--------+------------------+
| Sensor/Dataset        | Temporal | Spatial | Extent |     License      |
+=======================+==========+=========+========+==================+
| `Soil Grids (ISRIC)`_ | Present  | 250 m   | Global | `CC by-SA 4.0`_ |
+-----------------------+----------+---------+--------+------------------+

.. _Soil Grids (ISRIC): https://www.soilgrids.org/
.. _CC by-SA 4.0: https://creativecommons.org/licenses/by-sa/4.0/",

Agroecological Zones
~~~~~~~~~~~~~~~~~~~~

+---------------------------------------------------+----------+---------+--------+---------------------+
| Sensor/Dataset                                    | Temporal | Spatial | Extent |       License       |
+===================================================+==========+=========+========+=====================+
| `FAO - IIASA Global Agroecological Zones (GAEZ)`_ | 2000     | 8 km    | Global |  `Public Domain`_   |
+---------------------------------------------------+----------+---------+--------+---------------------+

.. _FAO - IIASA Global Agroecological Zones (GAEZ): http://www.fao.org/nr/gaez/en
.. _Public Domain: https://creativecommons.org/publicdomain/zero/1.0/"

Administrative Boundaries
~~~~~~~~~~~~~~~~~~~~~~~~~

+--------------------------------------------+----------+---------+--------+-------------------+
| Sensor/Dataset                             | Temporal | Spatial | Extent |      License      |
+============================================+==========+=========+========+===================+
| `Natural Earth Administrative Boundaries`_ | Present  | 10/50m  | Global | `Public Domain`_  |
+--------------------------------------------+----------+---------+--------+-------------------+

.. _Natural Earth Administrative Boundaries: http://www.naturalearthdata.com/
.. _Public Domain: https://creativecommons.org/publicdomain/zero/1.0/"

License
-------

|trends.earth| is free and open-source. It is licensed under the `GNU General 
Public License, version 2.0 or later 
<https://www.gnu.org/licenses/old-licenses/gpl-2.0.en.html>`_.

This site and the products of |trends.earth| are made available under the terms 
of the `Creative Commons Attribution 4.0 International License (CC BY 4.0) 
<https://creativecommons.org/licenses/by/4.0>`_. The boundaries and names used, 
and the designations used, in |trends.earth| do not imply official endorsement or 
acceptance by Conservation International Foundation, or its partner 
organizations and contributors. 
