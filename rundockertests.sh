#!/bin/bash

cat .env

source .env

docker pull "qgis/qgis":${QGIS_VERSION_TAG}

docker-compose up -d
sleep 10


docker-compose exec -T qgis-testing-environment sh -c "apt-get update"
docker-compose exec -T qgis-testing-environment sh -c "apt-get install -y python3-opencv"
docker-compose exec -T qgis-testing-environment qgis_testrunner.sh test_suite.test_package

docker-compose down
