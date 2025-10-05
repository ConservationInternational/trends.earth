#!/usr/bin/env bash

qgis_setup.sh LDMP

# FIX default installation because the sources must be in "trends.earth parent folder
rm -rf  /root/.local/share/QGIS/QGIS3/profiles/default/python/plugins/trends.earth
ln -sf /tests_directory/LDMP /root/.local/share/QGIS/QGIS3/profiles/default/python/plugins/trends.earth


## Updating trends.earth-schemas and trends.earth-algorithms versions in the requirements-testing file
#invoke set-version -v $(cat version.txt) --testing

# Upgrade pip to fix UNKNOWN package issue with pyproject.toml-only packages
# Older pip versions (< 24.0) don't properly handle PEP-517 builds from git/source
# See: https://stackoverflow.com/questions/78034052/unknown-project-name-and-version-number-for-my-own-pip-package
# Also upgrade setuptools and packaging to fix canonicalize_version() compatibility issues in QGIS 3.26
python3 -m pip install --no-cache-dir --upgrade pip setuptools packaging

# Install dependencies using python3 -m pip to ensure we use the upgraded pip
# The QGIS 3.26 container has packages with invalid version strings (e.g., '0.8.0-final0')
# Using python3 -m pip ensures we use the upgraded pip with better version parsing
# that doesn't choke on non-PEP-440 version strings in system packages
# The QGIS container has blinker 1.4 installed via distutils which can't be uninstalled
# Flask requires a newer blinker, so we install with --ignore-installed
python3 -m pip install --no-cache-dir --ignore-installed blinker -r /tests_directory/requirements-testing.txt
