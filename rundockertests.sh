#!/bin/bash
# Run docker tests on your local machine

PLUGIN_NAME="LDMP"

DOCKER_RUN_COMMAND="docker exec -it qgis-testing-environment sh -c"

git clone https://github.com/boundlessgeo/qgis-testing-environment-docker qgis-testing-environment
cd qgis-testing-environment && docker build -t qgis-testing-environment --build-arg QGIS_BRANCH=release-2_18 --build-arg LEGACY='true' .
sleep 10

# Setup
$DOCKER_RUN_COMMAND "qgis_setup.sh $PLUGIN_NAME"
$DOCKER_RUN_COMMAND "pip install paver"
$DOCKER_RUN_COMMAND "pip install boto3"
$DOCKER_RUN_COMMAND "cd /tests_directory && paver setup && paver package --tests"

# Run the tests
$DOCKER_RUN_COMMAND "DISPLAY=:99 QT_X11_NO_MITSHM=1 GSHOSTNAME=boundless-test qgis_testrunner.sh LDMP.test.dialog_settings_tests.run_all"
