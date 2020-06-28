@echo off
REM Run docker tests on your local machine

set PLUGIN_NAME="LDMP"
set CONTAINER=trendsearth_qgis_1
 
set DOCKER_RUN_COMMAND=docker exec -it %CONTAINER% sh -c

REM docker-compose down -v
docker-compose up -d

%DOCKER_RUN_COMMAND% "qgis_setup.sh %PLUGIN_NAME%"
%DOCKER_RUN_COMMAND% "rm -f  /root/.local/share/QGIS/QGIS3/profiles/default/python/plugins/%PLUGIN_NAME%"
%DOCKER_RUN_COMMAND% "ln -s /tests_directory/LDMP/ /root/.local/share/QGIS/QGIS3/profiles/default/python/plugins/%PLUGIN_NAME%"
docker cp trends.earth_test_user_credentials.json %CONTAINER%:/tests_directory/LDMP/test/trends.earth_test_user_credentials.json
docker cp trends.earth_admin_user_credentials.json %CONTAINER%:/tests_directory/LDMP/test/trends.earth_admin_user_credentials.json

REM Run the tests
%DOCKER_RUN_COMMAND% "cd /tests_directory && /usr/bin/test_runner/qgis_testrunner.sh LDMP.test.testplugin"
