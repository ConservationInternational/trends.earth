#!/bin/bash

docker-compose exec -T qgis-testing-environment qgis_testrunner.sh test_suite.test_package
