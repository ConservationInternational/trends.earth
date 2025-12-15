#!/bin/bash

cat .env

source .env

docker pull "qgis/qgis":${QGIS_VERSION_TAG}

docker compose down
docker compose rm
docker-compose up -d
