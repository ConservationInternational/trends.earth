# QGIS test image with the plugin's test dependencies preinstalled, so that
# containers do not need network access to PyPI or apt when they start.
ARG IMAGE=qgis/qgis
ARG QGIS_VERSION_TAG=release-3_34
FROM ${IMAGE}:${QGIS_VERSION_TAG}

ENV PIP_BREAK_SYSTEM_PACKAGES=1 \
    PIP_NO_CACHE_DIR=1

RUN set -eux; \
    missing=""; \
    command -v git >/dev/null 2>&1 || missing="$missing git"; \
    command -v unbuffer >/dev/null 2>&1 || missing="$missing expect"; \
    command -v pip3 >/dev/null 2>&1 || missing="$missing python3-pip"; \
    if [ -n "$missing" ]; then \
        apt-get update; \
        apt-get install -y --no-install-recommends $missing; \
        rm -rf /var/lib/apt/lists/*; \
    fi

# Older pip versions do not handle pyproject-only git requirements, and some
# QGIS images have distutils-installed packages (e.g. blinker) that pip cannot
# uninstall, hence --ignore-installed.
RUN python3 -m pip install --ignore-installed --upgrade pip setuptools packaging

COPY requirements-testing.txt /tmp/requirements-testing.txt
RUN python3 -m pip install --ignore-installed blinker \
        -r /tmp/requirements-testing.txt pytest python-dotenv coverage \
    && rm /tmp/requirements-testing.txt
