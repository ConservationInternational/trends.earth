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

from PyQt4 import QtGui, uic
from PyQt4.QtCore import Qt, QSettings

from qgis.core import QgsMessageLog
from qgis.utils import iface

mb = iface.messageBar()

site.addsitedir(os.path.abspath(os.path.dirname(__file__) + '/ext-libs'))

debug = QSettings().value('LDMP/debug', True)

def log(message, level=QgsMessageLog.INFO):
    if debug:
        QgsMessageLog.logMessage(message, tag="LDMP", level=level)

class DownloadError(Exception):
     def __init__(self, message):
        self.message = message

def download_file(url, filename):
    total_size = requests.get(url, stream=True).headers['Content-length']
    # TODO: Set dialog box label to include size of file download
    total_size = int(total_size)
    bytes_dl = 0

    if total_size < 1e5:
        total_size_pretty = '{:.2f} KB'.format(round(total_size/1024, 2))
    else:
        total_size_pretty = '{:.2f} MB'.format(round(total_size*1e-6, 2))
    
    log('Downloading {} ({}) to {}'.format(url, total_size_pretty, filename))

    progressMessageBar = iface.messageBar().createMessage("Downloading {} ({})...".format(os.path.basename(filename), total_size_pretty))
    progress = QtGui.QProgressBar()
    progress.setMaximum(1)
    progress.setAlignment(Qt.AlignLeft|Qt.AlignVCenter)
    progressMessageBar.layout().addWidget(progress)
    iface.messageBar().pushWidget(progressMessageBar, iface.messageBar().INFO)

    r = requests.get(url, stream=True)
    with open(filename, 'wb') as f:
        for chunk in r.iter_content(chunk_size=8192): 
            if chunk: # filter out keep-alive new chunks
                f.write(chunk)
                bytes_dl += len(chunk)
                progress.setValue(float(bytes_dl) / total_size)

    iface.messageBar().popWidget(progressMessageBar)
    iface.messageBar().pushMessage("Downloaded", "Finished downloading {}.".format(os.path.basename(filename)), level=0, duration=5)

    if bytes_dl != total_size:
        raise DownloadError('Final file size does not match expected')
        log("Download {} file size didn't match expected".format(url))
        return False
    else:
        log("Download of {} complete".format(url))

def read_json(file):
    filename = os.path.join(os.path.dirname(__file__), 'data', file)
    if not os.path.exists(filename):
        try:
            download_file('https://landdegradation.s3.amazonaws.com/Sharing/{}'.format(file), filename)
        except requests.exceptions.ConnectionError:
            mb.pushMessage("Error", "Unable to access internet. Check your internet connection.", level=1, duration=5)
            return None
    else:
        # If not found, offer to download the files from github or to load them 
        # from a local folder
        # TODO: Dialog box with two options:
        #   1) Download
        #   2) Load from local folder
        pass

    with gzip.GzipFile(filename, 'r') as fin:
        json_bytes = fin.read()
        json_str = json_bytes.decode('utf-8')

    return json.loads(json_str)

admin_0 = read_json('admin_0.json.gz')
QSettings().setValue('LDMP/admin_0', json.dumps(admin_0))

admin_1 = read_json('admin_1.json.gz')
QSettings().setValue('LDMP/admin_1', json.dumps(admin_1))

# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name
    """Load LDMPPlugin class from file LDMP.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """

    from LDMP.ldmp import LDMPPlugin
    return LDMPPlugin(iface)
