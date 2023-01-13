#!/usr/bin/env bash

qgis_setup.sh LDMP

# FIX default installation because the sources must be in "trends.earth parent folder
rm -rf  /root/.local/share/QGIS/QGIS3/profiles/default/python/plugins/trends.earth
ln -sf /tests_directory/LDMP /root/.local/share/QGIS/QGIS3/profiles/default/python/plugins/trends.earth


## Updating trends.earth-schemas and trends.earth-algorithms versions in the requirements-testing file
#invoke set-version -v $(cat version.txt) --testing

pip3 install -r /tests_directory/requirements-testing.txt
