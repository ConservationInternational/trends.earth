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
import requests
import re
import crcmod.predefined

from PyQt4 import QtGui, uic
from PyQt4.QtCore import Qt

from qgis.utils import iface

from . import log

from DlgDownload import Ui_DlgDownload

class DownloadError(Exception):
     def __init__(self, message):
        self.message = message

def check_hash(file, expected):
    BUF_SIZE = 65536
    crc = crcmod.predefined.mkCrcFun('crc-32-c')
    with open(file, 'rb') as f:
        while True:
            data = f.read(BUF_SIZE)
            if not data:
                break
            crc.update(data)
    if crc.crcValue == expected:
        return True
    else:
        log("Failed verification of file hash for {}. Expected {}, but got {}.".format(filename, expected, crc.crcValue), 2)
        return False

def download_file(url, filename):
    total_size = requests.get(url, stream=True).headers['Content-length']
    # TODO: Set dialog box label to include size of file download
    total_size = int(total_size)
    bytes_dl = 0

    if total_size < 1e5:
        total_size_pretty = '{:.2f} KB'.format(round(total_size/1024, 2))
    else:
        total_size_pretty = '{:.2f} MB'.format(round(total_size*1e-6, 2))
    
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

    if bytes_dl != total_size:
        #TODO: have a cleaner download error message
        raise DownloadError

    h = requests.head(url)
    try:
        #TODO not sure why this isn't working...
        expected_crc32c = re.search('crc32c=(.+?), md5=', h.headers['x-goog-hash']).group(1)
        if not check_hash(filename, expected_crc32c):
            log("File hash doesn't match expected value for {}.".format(filename), 2)
        else:
            log("File hash verified for {}.".format(filename))
    except AttributeError:
        log("CRC32c file hash not found in header for {}. Skipping hash check. WARNING file may not be complete.".format(filename), 2)
        #TODO delete file and suggest attempting download again

    iface.messageBar().popWidget(progressMessageBar)
    iface.messageBar().pushMessage("Downloaded", "Finished downloading {}.".format(os.path.basename(filename)), level=0, duration=5)

class DlgDownload(QtGui.QDialog, Ui_DlgDownload):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgDownload, self).__init__(parent)
        # Set up the user interface from Designer.
        # After setupUI you can access any designer object by doing
        # self.<objectname>, and you can use autoconnect slots - see
        # http://qt-project.org/doc/qt-4.8/designer-using-a-ui-file.html
        # #widgets-and-dialogs-with-auto-connect
        self.setupUi(self)
