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
import json

with open(os.path.join(os.path.dirname(__file__), 'trends.earth_test_user_credentials.json'), 'r') as fin:
    regular_keys = json.load(fin)
with open(os.path.join(os.path.dirname(__file__), 'trends.earth_admin_user_credentials.json'), 'r') as fin:
    admin_keys = json.load(fin)
