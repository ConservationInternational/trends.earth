@echo off
REM Run docker tests on your local machine

set QGIS_VERSION_TAG=release-3_26
set WITH_PYTHON_PEP=true
set MUTE_LOGS=false
set IMAGE=qgis/qgis
set ON_TRAVIS=false

REM docker-compose down -v
docker-compose up -d

docker-compose exec -T qgis-testing-environment sh -c "apt-get update"
docker-compose exec -T qgis-testing-environment sh -c "apt-get install -y python3-opencv"
docker-compose exec -T qgis-testing-environment qgis_testrunner.sh LDMP.test.testplugin