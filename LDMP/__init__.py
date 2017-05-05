# -*- coding: utf-8 -*-
"""
/***************************************************************************
 LDMP
                                 A QGIS plugin
 This plugin supports assessments of land degradation for UNCCD reporting and tracking progress of SDG Target 15.3.1.
                              -------------------
        begin                : 2017-05-05
        copyright            : (C) 2017 by Conservation International
        email                : gef-ldmp@conservation.org
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
 This script initializes the plugin, making it known to QGIS.
"""

__author__ = 'Conservation International'
__date__ = '2017-05-05'
__copyright__ = '(C) 2017 by Conservation International'


# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name
    """Load LDMP class from file LDMP.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    #
    from .land_degradation import LDMPPlugin
    return LDMPPlugin()
