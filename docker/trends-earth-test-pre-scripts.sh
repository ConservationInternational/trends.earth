#!/usr/bin/env bash

qgis_setup.sh

# FIX default installation because the sources must be in "trends.earth parent folder
rm -rf  /root/.local/share/QGIS/QGIS3/profiles/default/python/plugins/trends.earth
ln -sf /tests_directory/LDMP /root/.local/share/QGIS/QGIS3/profiles/default/python/plugins/trends.earth
ln -sf /tests_directory/LDMP /usr/share/qgis/python/plugins/trends.earth

pip3 install -r /tests_directory/requirements.txt
pip3 install -r /tests_directory/requirements-dev.txt
