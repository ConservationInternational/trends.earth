#!/bin/bash

cat .env

source .env

docker pull "qgis/qgis":${QGIS_VERSION_TAG}
docker-compose up -d
sleep 10

docker-compose exec -T qgis-testing-environment qgis_testrunner.sh LDMP.test.testplugin
