@echo off

docker-compose exec -T qgis-testing-environment qgis_testrunner.sh LDMP.test.testplugin
