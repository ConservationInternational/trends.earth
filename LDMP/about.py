"""
/***************************************************************************
 LDMP - A QGIS plugin
 This plugin supports monitoring and reporting of land degradation to the UNCCD
 and in support of the SDG Land Degradation Neutrality (LDN) target.
                              -------------------
        begin                : 2017-05-23
        git sha              : $Format:%H$
        copyright            : (C) 2017 by Conservation International
        email                : trends.earth@conservation.org
 ***************************************************************************/
"""

from pathlib import Path

from qgis.PyQt import QtWidgets, uic

from LDMP import __release_date__, __revision__, __version__

Ui_DlgAbout, _ = uic.loadUiType(str(Path(__file__).parent / "gui/DlgAbout.ui"))


class DlgAbout(QtWidgets.QDialog, Ui_DlgAbout):
    def __init__(self, parent=None):
        """Constructor."""
        super().__init__(parent)

        self.setupUi(self)

        # Add version number to about dialog
        version = "{}<br>(revision {}, {})".format(
            __version__, __revision__, __release_date__
        )
        self.textBrowser.setText(
            self.textBrowser.text().replace("VERSION_NUMBER", version)
        )
