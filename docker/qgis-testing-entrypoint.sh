#!/usr/bin/env bash

# Docker entrypoint file intended for docker-compose recipe for running unittests

set -e

source /tests_directory/docker/trends-earth-test-pre-scripts.sh

# Run the image's virtual display service.
if command -v supervisord >/dev/null 2>&1; then
	supervisord -c /etc/supervisor/supervisord.conf &
else
	Xvfb :99 -screen 0 1024x768x24 -nolisten tcp &
fi

# Wait for XVFB
sleep 10

exec "$@"
