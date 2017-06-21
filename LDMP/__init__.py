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

import os
import gzip
import json
import site

from PyQt4.QtCore import QSettings

site.addsitedir(os.path.abspath(os.path.dirname(__file__) + '/ext-libs'))

def read_json(file):
    with gzip.GzipFile(os.path.join(os.path.dirname(__file__), 'data', file), 'r') as fin:
        json_bytes = fin.read()
        json_str = json_bytes.decode('utf-8')
    return json.loads(json_str)

admin_0 = read_json('admin_0.json.gz')
QSettings().setValue('LDMP/admin_0', json.dumps(admin_0))

admin_1 = read_json('admin_1.json.gz')
QSettings().setValue('LDMP/admin_1', json.dumps(admin_1))

# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name
    """Load LDMP class from file LDMP.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """

    from .ldmp import LDMP
    return LDMP(iface)
