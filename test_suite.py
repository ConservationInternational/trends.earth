import sys
import os
import unittest
import qgis  # NOQA  For SIP API to V2 if run outside of QGIS

try:
    from pip import main as pipmain
except ImportError:
    from pip._internal import main as pipmain

try:
    import coverage
except ImportError:
    pipmain(['install', 'coverage'])
    import coverage
import tempfile
from osgeo import gdal
from qgis.PyQt import Qt

from qgis.core import Qgis


def _run_tests(test_suite, package_name, with_coverage=False):
    """Core function to test a test suite."""
    count = test_suite.countTestCases()

    version = str(Qgis.QGIS_VERSION_INT)
    version = int(version)

    print('########')
    print('%s tests has been discovered in %s' % (count, package_name))
    print('QGIS : %s' % version)
    print('Python GDAL : %s' % gdal.VersionInfo('VERSION_NUM'))
    print('QT : %s' % Qt.QT_VERSION_STR)
    print('Run slow tests : %s' % (not os.environ.get('ON_TRAVIS', False)))
    print('########')
    if with_coverage:
        cov = coverage.Coverage(
            source=['./'],
            omit=['*/test/*', './definitions/*'],
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
        with open(report.name, 'r') as fin:
            print(fin.read())


def test_package(package='LDMP.test'):
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
