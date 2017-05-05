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
"""

__author__ = 'Conservation International'
__date__ = '2017-05-05'
__copyright__ = '(C) 2017 by Conservation International'

# This will get replaced with a git SHA1 when you do a git archive

__revision__ = '$Format:%H$'

import os
import sys
import inspect

from processing.core.Processing import Processing
from land_degradation_provider import LDMPProvider

cmd_folder = os.path.split(inspect.getfile(inspect.currentframe()))[0]

if cmd_folder not in sys.path:
    sys.path.insert(0, cmd_folder)


class LDMPPlugin:

    def __init__(self):
        self.provider = LDMPProvider()

    def initGui(self):
        Processing.addProvider(self.provider)

    def unload(self):
        Processing.removeProvider(self.provider)
