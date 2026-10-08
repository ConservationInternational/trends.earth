#!/usr/bin/env bash
set -Eeuo pipefail

# Usage: ./run_tests.sh [qgis-version-tag] [test-target]
# Examples: ./run_tests.sh 3.44
#           ./run_tests.sh 4.2-trixie
# Set SHOW_DOCKER_LOGS=true to print container logs on failure.

read_env_setting() {
	local key="$1" line
	[[ -f .env ]] || return 0
	while IFS= read -r line || [[ -n "$line" ]]; do
		line="${line#$'\xef\xbb\xbf'}"
		line="${line%$'\r'}"
		if [[ "$line" == "$key="* ]]; then
			printf '%s' "${line#*=}"
			return 0
		fi
	done < .env
}

DOTENV_QGIS_VERSION_TAG="$(read_env_setting QGIS_VERSION_TAG)"
DOTENV_IMAGE="$(read_env_setting IMAGE)"
QGIS_VERSION_TAG="${1:-${QGIS_VERSION_TAG:-${DOTENV_QGIS_VERSION_TAG:-release-3_34}}}"
TEST_TARGET="${2:-test_suite.test_package}"
IMAGE="${IMAGE:-${DOTENV_IMAGE:-qgis/qgis}}"
SERVICE="${SERVICE:-qgis-testing-environment}"
COMPOSE_PROJECT="${COMPOSE_PROJECT:-trends-earth-tests}"
STARTUP_WAIT="${STARTUP_WAIT:-60}"
export QGIS_VERSION_TAG IMAGE SERVICE
export ON_TRAVIS="${ON_TRAVIS:-true}"
export MUTE_LOGS="${MUTE_LOGS:-true}"
export WITH_PYTHON_PEP="${WITH_PYTHON_PEP:-true}"

cleanup() {
	local exit_code=$?
	if [[ "${SHOW_DOCKER_LOGS:-false}" == "true" ]]; then
		docker compose -p "$COMPOSE_PROJECT" logs "$SERVICE" >&2 || true
	fi
	if [[ "${KEEP_TEST_CONTAINERS:-false}" != "true" ]]; then
		docker compose -p "$COMPOSE_PROJECT" down -v || true
	fi
	exit "$exit_code"
}
trap cleanup EXIT

echo "Building QGIS test image from: ${IMAGE}:${QGIS_VERSION_TAG}"
docker compose -p "$COMPOSE_PROJECT" build --pull "$SERVICE"

echo "Starting QGIS test environment"
docker compose -p "$COMPOSE_PROJECT" up -d "$SERVICE"
if [[ "$STARTUP_WAIT" != "0" ]]; then
	sleep "$STARTUP_WAIT"
fi
docker compose -p "$COMPOSE_PROJECT" ps

echo "Testing QGIS version and runtime"
docker compose -p "$COMPOSE_PROJECT" exec -T "$SERVICE" python3 -c '
import qgis.core
import osgeo.gdal as gdal
import sys
print("QGIS", qgis.core.Qgis.QGIS_VERSION, "GDAL", gdal.VersionInfo("RELEASE_NAME"), "Python", sys.version.split()[0])
'

echo "Running tests: ${TEST_TARGET}"
docker compose -p "$COMPOSE_PROJECT" exec -T "$SERVICE" qgis_testrunner.sh "$TEST_TARGET"
