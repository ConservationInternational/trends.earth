#!/bin/bash
# Run docker tests on your local machine

PLUGIN_NAME="LDMP"
export QGIS_VERSION_TAG="master_2"

docker-compose down -v
docker-compose up -d
sleep 10


DOCKER_RUN_COMMAND="docker-compose exec qgis-testing-environment sh -c"

# Setup
$DOCKER_RUN_COMMAND "qgis_setup.sh $PLUGIN_NAME"
$DOCKER_RUN_COMMAND "pip install paver"
$DOCKER_RUN_COMMAND "pip install boto3"
$DOCKER_RUN_COMMAND "cd /tests_directory && paver setup && paver package --tests"

# Run the tests
$DOCKER_RUN_COMMAND "DISPLAY=:99 QT_X11_NO_MITSHM=1 GSHOSTNAME=boundless-test qgis_testrunner.sh LDMP.test.dialog_settings_tests.run_all"
