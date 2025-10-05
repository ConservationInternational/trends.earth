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
# Use --ignore-installed to bypass system packages that might have invalid version strings (e.g., '0.8.0-final0')
pip3 install --no-cache-dir --ignore-installed --upgrade pip setuptools packaging

# Install dependencies with --ignore-installed flag to handle distutils-installed packages
# The QGIS container has blinker 1.4 installed via distutils which can't be uninstalled
# Flask requires a newer blinker, so we ignore the old system package
pip3 install --no-cache-dir --ignore-installed blinker -r /tests_directory/requirements-testing.txt
