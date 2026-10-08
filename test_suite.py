import os
import sys
import unittest

import qgis  # NOQA  For SIP API to V2 if run outside of QGIS

try:
    from pip import main as pipmain
except ImportError:
    from pip._internal import main as pipmain

try:
    import coverage
except ImportError:
    pipmain(["install", "coverage"])
    import coverage
import tempfile

from osgeo import gdal
from qgis.core import Qgis
from qgis.PyQt.QtCore import QT_VERSION_STR


def _run_tests(test_suite, package_name, with_coverage=False):
    """Core function to test a test suite."""
    count = test_suite.countTestCases()

    version = str(Qgis.QGIS_VERSION_INT)
    version = int(version)

    print("########")
    print("%s tests has been discovered in %s" % (count, package_name))
    print("QGIS : %s" % version)
    print("Python GDAL : %s" % gdal.VersionInfo("VERSION_NUM"))
    print("QT : %s" % QT_VERSION_STR)
    print("Run slow tests : %s" % (not os.environ.get("ON_TRAVIS", "")))
    print("########")
    if with_coverage:
        cov = coverage.Coverage(
            source=["./"],
            omit=["*/test/*", "./definitions/*"],
        )
        cov.start()

    unittest.TextTestRunner(verbosity=3, stream=sys.stdout).run(test_suite)

    if with_coverage:
        cov.stop()
        cov.save()
        report = tempfile.NamedTemporaryFile(delete=False)
        cov.report(file=report)
        # Produce HTML reports in the `htmlcov` folder and open index.html
        # cov.html_report()
        report.close()
        with open(report.name, "r") as fin:
            print(fin.read())


def test_package(package="test"):
    """Test package.
    This function is called by Github actions or travis without arguments.
    :param package: The package to test.
    :type package: str
    """
    test_loader = unittest.defaultTestLoader
    try:
        test_suite = test_loader.discover(package)
    except ImportError:
        test_suite = unittest.TestSuite()
    _run_tests(test_suite, package)


def test_e2e(package="test"):
    """Run the opt-in end-to-end tests against the live Trends.Earth API.

    Requires TE_E2E_CLIENT_ID and TE_E2E_CLIENT_SECRET (an OAuth2 service
    credential for the e2e test user); see test/README.md.
    """
    os.environ["TE_E2E_ENABLE"] = "1"
    if not (
        os.environ.get("TE_E2E_CLIENT_ID", "").strip()
        and os.environ.get("TE_E2E_CLIENT_SECRET", "").strip()
    ):
        print("TE_E2E_CLIENT_ID/TE_E2E_CLIENT_SECRET not set; e2e tests will skip")
    # Discover from the same root as test_package so the stdlib "test" package
    # does not shadow ours; the pattern limits the run to the e2e module.
    test_suite = unittest.defaultTestLoader.discover(
        package, pattern="test_remote_pipelines.py"
    )
    _run_tests(test_suite, package)
