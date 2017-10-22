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
import requests
import json
import site

from PyQt4 import QtGui, QtCore, uic

from qgis.core import QgsMessageLog
from qgis.utils import iface

site.addsitedir(os.path.abspath(os.path.dirname(__file__) + '/ext-libs'))

debug = QtCore.QSettings().value('LDMP/debug', True)

def log(message, level=QgsMessageLog.INFO):
    if debug:
        QgsMessageLog.logMessage(message, tag="LDMP", level=level)

from LDMP.download import Download
def read_json(file):
    filename = os.path.join(os.path.dirname(__file__), 'data', file)
    if not os.path.exists(filename):
        # TODO: Check a crc checksum on these files to catch partial downloads 
        # other potential problems with the .JSONs. Delete the files if there 
        # is an error.
        #
        # If not found, offer to download the files from github or to load them 
        # from a local folder
        # TODO: Dialog box with two options:
        #   1) Download
        #   2) Load from local folder
        worker = Download('https://landdegradation.s3.amazonaws.com/Sharing/{}'.format(file), filename)
        worker.start()
        resp = worker.get_resp()
        if not resp:
            return None

    with gzip.GzipFile(filename, 'r') as fin:
        json_bytes = fin.read()
        json_str = json_bytes.decode('utf-8')

    return json.loads(json_str)

admin_bounds_key = read_json('admin_bounds_key.json.gz')
QtCore.QSettings().setValue('LDMP/admin_bounds_key', json.dumps(admin_bounds_key))

# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name
    """Load LDMPPlugin class from file LDMP.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """

    from LDMP.ldmp import LDMPPlugin
    return LDMPPlugin(iface)
