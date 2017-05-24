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
        email                : GEF-LDMP@conservation.org
 ***************************************************************************/
"""

# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name
    """Load LDMP class from file LDMP.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    #
    from .ldmp import LDMP
    return LDMP(iface)

# TODO check global settings object and load:
#  - adm_bounds level 1 (if sha hash of data varies from that stored in global 
#  settings)
#  - adm_bounds level 2 (if sha hash of data varies from that stored in global 
#  settings)
