@echo off
REM Run docker tests on your local machine

set PLUGIN_NAME="LDMP"
set QGIS_VERSION_TAG=master
set CONTAINER=trendsearth_qgis_1
 
set DOCKER_RUN_COMMAND=docker exec -it %CONTAINER% sh -c

docker-compose down -v
docker-compose up -d

REM Setup docker instance
%DOCKER_RUN_COMMAND% "qgis_setup.sh %PLUGIN_NAME%"
%DOCKER_RUN_COMMAND% "cd /tests_directory && git submodule update --init --recursive"
%DOCKER_RUN_COMMAND% "cd /tests_directory && invoke zipfile-build -c -t -f /LDMP.zip -p python3"
%DOCKER_RUN_COMMAND% "unzip /LDMP.zip -d /"
%DOCKER_RUN_COMMAND% "rm -f  /root/.local/share/QGIS/QGIS3/profiles/default/python/plugins/%PLUGIN_NAME%"
%DOCKER_RUN_COMMAND% "ln -s /LDMP/ /root/.local/share/QGIS/QGIS3/profiles/default/python/plugins/%PLUGIN_NAME%"
docker cp trends.earth_test_user_credentials.json %CONTAINER%:/LDMP/test/trends.earth_test_user_credentials.json
docker cp trends.earth_admin_user_credentials.json %CONTAINER%:/LDMP/test/trends.earth_admin_user_credentials.json

REM Run the tests
%DOCKER_RUN_COMMAND% "cd /LDMP && qgis_testrunner.sh LDMP.test.testplugin"
