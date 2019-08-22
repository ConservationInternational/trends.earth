Development
===========

|trends.earth| is free and open-source software, licensed under the `GNU 
General Public License, version 2.0 or later 
<https://www.gnu.org/licenses/old-licenses/gpl-2.0.en.html>`_.

There are a number of components to the |trends.earth| tool. The first is a 
QGIS plugin supporting calculation of indicators, access to raw data, 
reporting, and production of print maps . The code for the plugin, and further 
instructions on installing it if you want to modify the code, are in 
`trends.earth <https://github.com/ConservationInternational/trends.earth>`_ 
github repository.

The |trends.earth| QGIS plugin is supported by a number of different Python 
scripts that allow calculation of the various indicators on Google Earth Engine 
(GEE). These scripts sit in the "gee" subfolder of that github repository. The 
GEE scripts are supported by the `landdegradation` Python module, which 
includes code for processing inputs and outputs for the plugin, as well as 
other common functions supporting calculation of NDVI integrals, statistical 
significance, and other shared code. The code for this module is available in 
the `landdegradation 
<https://github.com/ConservationInternational/landdegradation>`_ repository on 
Github.

Further details are below on how to contribute to Trends.Earth by working on 
the plugin code, by modifying the processing code, or by contributing to 
translating the website and plugin.

Modifying the QGIS Plugin code
______________________________


Modifying the Earth Engine processing code
__________________________________________

Testing a script locally
------------------------

Working with translations
_________________________


Contributing as a translator
----------------------------

Updating plugin translations
----------------------------
