@echo off
REM Run docker tests on your local machine

set PLUGIN_NAME="LDMP"
set CONTAINER=trendsearth_qgis_1
 
set DOCKER_RUN_COMMAND=docker exec -it %CONTAINER% sh -c

REM docker-compose down -v
docker-compose up -d

REM Setup docker instance
%DOCKER_RUN_COMMAND% "openssl aes-256-cbc -K $encrypted_e3ee5199e171_key -iv $encrypted_e3ee5199e171_iv -in travis_secrets.tar.gz.enc -out travis_secrets.tar.gz -d"
%DOCKER_RUN_COMMAND% "tar xzvf travis_secrets.tar.gz"
%DOCKER_RUN_COMMAND% "export AWS_SHARED_CREDENTIALS_FILE=aws_credentials.json"
%DOCKER_RUN_COMMAND% "qgis_setup.sh LDMP"
%DOCKER_RUN_COMMAND% "cd /tests_directory && git submodule update --init --recursive"
%DOCKER_RUN_COMMAND% "cd /tests_directory && invoke testdata-sync"
%DOCKER_RUN_COMMAND% "cd /tests_directory && invoke zipfile-build -c -t -f /LDMP.zip --python python3"
%DOCKER_RUN_COMMAND% "unzip -qq /LDMP.zip -d /""
%DOCKER_RUN_COMMAND% "docker cp trends.earth_test_user_credentials.json trendsearth_qgis_1:/LDMP/test/trends.earth_test_user_credentials.json"
%DOCKER_RUN_COMMAND% "docker cp trends.earth_admin_user_credentials.json trendsearth_qgis_1:/LDMP/test/trends.earth_admin_user_credentials.json"
%DOCKER_RUN_COMMAND% "rm -f  /root/.local/share/QGIS/QGIS3/profiles/default/python/plugins/LDMP"
%DOCKER_RUN_COMMAND% "ln -s /LDMP/ /root/.local/share/QGIS/QGIS3/profiles/default/python/plugins/LDMP"
%DOCKER_RUN_COMMAND% "cd /LDMP && qgis_testrunner.sh LDMP.test.testplugin"

%DOCKER_RUN_COMMAND% "qgis_setup.sh %PLUGIN_NAME%"
%DOCKER_RUN_COMMAND% "cd /tests_directory && git submodule update --init --recursive"
%DOCKER_RUN_COMMAND% "cd /tests_directory && invoke testdata-sync"
%DOCKER_RUN_COMMAND% "cd /tests_directory && invoke zipfile-build -t -f /LDMP.zip --python python3"
%DOCKER_RUN_COMMAND% "unzip -qq -o /LDMP.zip -d /"
%DOCKER_RUN_COMMAND% "rm -f  /root/.local/share/QGIS/QGIS3/profiles/default/python/plugins/%PLUGIN_NAME%"
%DOCKER_RUN_COMMAND% "ln -s /LDMP/ /root/.local/share/QGIS/QGIS3/profiles/default/python/plugins/%PLUGIN_NAME%"
docker cp trends.earth_test_user_credentials.json %CONTAINER%:/LDMP/test/trends.earth_test_user_credentials.json
docker cp trends.earth_admin_user_credentials.json %CONTAINER%:/LDMP/test/trends.earth_admin_user_credentials.json

REM Run the tests
%DOCKER_RUN_COMMAND% "cd /LDMP && qgis_testrunner.sh LDMP.test.testplugin"
