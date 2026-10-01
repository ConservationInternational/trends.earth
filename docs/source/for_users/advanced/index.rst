.. _advanced:

Advanced
========

Installing Numba for local calculations
---------------------------------------

Numba can speed up some local Trends.Earth calculations. It is not included by 
default with the Trends.Earth installer given limitations on packaging binaries 
for distribution via the standard QGIS repositories. To use it, install it in the
Python environment used by QGIS. Close QGIS before installing packages, and 
restart it afterward.

Windows
~~~~~~~

Open the **OSGeo4W Shell** installed with your QGIS installation (use the
shell for the same QGIS version you run Trends.Earth in). Run::

    python -m pip install --user numba

If the shell reports that pip is unavailable, or the installation conflicts
with packages supplied by QGIS, consult your QGIS distribution's package
manager rather than replacing its bundled packages.

macOS
~~~~~

Open **Plugins > Python Console** in QGIS and run::

    import sys
    print(sys.executable)

Quit QGIS. If the printed path points to a Python executable, use that exact
path in Terminal (substitute your own path for ``/path/to/qgis/python3``)::

    "/path/to/qgis/python3" -m pip install --user numba

If the path points to the QGIS application instead of Python, use the Python
interpreter provided by your QGIS installation. For example, with a Homebrew
installation, use the Python from the same Homebrew environment as QGIS; with
a standalone QGIS app, check the app bundle for its Python interpreter.

Linux
~~~~~

For QGIS installed from your distribution's package manager, install the
matching Numba package from that same distribution. For example, on
Debian/Ubuntu::

    sudo apt install python3-numba

If QGIS instead uses a separate Python environment, activate that environment
and install Numba there::

    python -m pip install numba

To check the result on any platform, restart QGIS and run this in **Plugins >
Python Console**::

    import numba
    print(numba.__version__)

If this raises ``ModuleNotFoundError``, Numba was installed in a different
Python environment. Check ``sys.executable`` and ``sys.prefix`` in the QGIS
Python Console and select the Python environment associated with that QGIS
installation before trying again.