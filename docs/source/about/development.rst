Development
===========

|trends.earth| is free and open-source software, licensed under the `GNU 
General Public License, version 2.0 or later 
<https://www.gnu.org/licenses/old-licenses/gpl-2.0.en.html>`_.

There are a number of components to the |trends.earth| tool. The first is a 
QGIS plugin supporting calculation of indicators, access to raw data, 
reporting, and production of print maps . The code for the plugin, and further 
instructions on installing it if you want to modify the code, are in 
`trends.earth <https://github.com/ConservationInternational/trends.earth>`_ 
github repository.

The |trends.earth| QGIS plugin is supported by a number of different Python 
scripts that allow calculation of the various indicators on Google Earth Engine 
(GEE). These scripts sit in the "gee" subfolder of that github repository. The 
GEE scripts are supported by the `landdegradation` Python module, which 
includes code for processing inputs and outputs for the plugin, as well as 
other common functions supporting calculation of NDVI integrals, statistical 
significance, and other shared code. The code for this module is available in 
the `landdegradation 
<https://github.com/ConservationInternational/landdegradation>`_ repository on 
Github.

Further details are below on how to contribute to Trends.Earth by working on 
the plugin code, by modifying the processing code, or by contributing to 
translating the website and plugin.

Modifying the QGIS Plugin code
______________________________


Downloading the trends.earth code
---------------------------------

The Trends.Earth code for both the plugin and the Google Earth Engine scripts 
that support it are located on github in the `trends.earth
<https://github.com/ConservationInternational/trends.earth>`_ repository. Clone 
this repository to a convenient place on your machine in order to ensure you 
have the latest version of the code.

There are a number of different branches of the trends.earth repository that 
are under active development. As the plugin does not yet officially support 
QGIS3, the "qgis2" branch is where most development work is happening. The 
"master" branch has some initial changes to support on the "qgis3", and will 
eventually become the primary place for development once that version is 
released.

Installing dependencies
-----------------------

Python
~~~~~~

The plugin is coded in Python. In addition to being used to run the plugin 
through QGIS, Python is also used to support managing the plugin (changing the 
version, installing development versions, etc.). Though Python is included with 
QGIS, you will also need a local version of Python that you can setup with the 
software needed to manage the plugin. The easiest way to manage multiple 
versions of Python is through the `Anaconda distribution 
<https://www.anaconda.com>`_. For work developing the plugin, Python 
3 is required. To download Python 3.7 (recommended) though Anaconda,
`see this page <https://www.anaconda.com/distribution/#download-section>`_.

Python dependencies
~~~~~~~~~~~~~~~~~~~

In order to work with the trends.earth code, you need to have Invoke
installed on your machine, as well as a number of other packages that are used 
for managing the documentation, translations, etc. These packages are all 
listed in the "dev" requirements file for Trends.Earth, so they can be 
installed by navigating in a command prompt to the root of the trends.earth 
code folder and typing::

   pip install -r requirements-dev.txt

.. note::
   If you are using Anaconda, you will first want to activate a Python 3.7 
   virtual environment before running the above command (and any of the other 
   invoke commands listed on the page). One way to do this is by starting an 
   "Anaconda prompt", by `following the instructions on this Anaconda page
   <https://docs.anaconda.com/anaconda/user-guide/getting-started/#write-a-python-program-using-anaconda-prompt-or-terminal>`_.

PyQt4
~~~~~

PyQt4 is the graphics toolkit used by QGIS2. To compile the user interface for 
Trends.Earth you need to install PyQt4. The best source for this package is 
from the set of packages maintained by Christoph Gohlke at UC Irvine. To 
download PyQt4, select `the appropriate package from this page 
<https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyqt4>`_. Choose the appropriate 
file for the version of Python you are using. For example, if you are using 
Python 2.7, choose the version with "cp27" in the filename. If you are using 
Python 3.7, choose the version with "cp37" in the filename. Choose "amd64" for 
64-bit python, and "win32" for 32-bit python.

After downloading from the above link, use ``pip`` to install it. For example, 
for the 64-bit wheel for Python 3.7, you would run::

   pip install PyQt4-4.11.4-cp37-cp37m-win_amd64.whl

Changing the version of the plugin
----------------------------------

The convention for Trends.Earth is that version numbers ending in an odd number
(for example 0.65) are development versions, while versions ending in an even 
number (for example (0.66) are release versions. Development versions of the 
plugin are never released via the QGIS repository, so they are never seen by 
normal users of the plugin. Odd-numbered development versions are used by the 
Trends.Earth development team while testing new features prior to their public 
release.

If you wish to make changes to the code and have downloaded a public release of 
the plugin (one ending in an even number), the first step is to update the 
version of the plugin to the next sequential odd number. So, for example, if 
you downloaded version 0.66 of the plugin, you would need to update the version 
to be 0.67 before you started making your changes. There are several places in 
the code where the version is mentioned (as well as within every GEE script) so 
there is an invoke task to assist with changing the version. To change the 
version to be 0.67, you would run::

   invoke set-version -v 0.67

Running the above command will update the version number every place it is 
referenced in the code. To avoid confusion, never change the version to one 
that has already been released - always INCREASE the value of the version tag 
to the next odd number.

Testing changes to the plugin
-----------------------------

After making changes to the plugin code, you will need to test them to ensure 
the plugin behaves as expected, and to ensure no bugs or errors come up. The 
plugin should go through extensive testing before it is released to the QGIS 
repository (where it can be accessed by other users) to ensure that any changes
to the code do not break the plugin.

To test any changes that you have made to the plugin within QGIS, you will need 
to install it locally. There are invoke tasks that assist with this process. 
The first step prior to installing the plugin is ensuring that you have setup 
the plugin with all of the dependencies that it needs in order to run from 
within QGIS. To do this, run::

   invoke plugin-setup

The above task only needs to be run immediately after downloading the 
trends.earth code, or if any changes are made to the dependencies for the 
plugin. By default ``plugin-setup`` will re-use any cached files on your 
machine. To start from scratch, add the ``-c`` (clean) flag to the above 
command.

After running ``plugin-setup``, you are ready to install the plugin to the QGIS 
plugins folder on your machine. To do this, run::

  invoke plugin-install

After running the above command, you will need to either 1) restart QGIS, or 2) 
use the `plugin reloader <https://plugins.qgis.org/plugins/plugin_reloader/>`_ 
to reload the Trends.Earth plugin in order to see the effects of the changes 
you have made.

Note that by default ``plugin-install`` will overwrite any existing plugin 
files on your machine, but leave in place any data (adminstrative boundaries, 
etc.) that the plugin might have downloaded. To start from scratch, add the 
``-c`` (clean) flag to the above command. You may need to close QGIS in order 
to succesfully perform a clean install of the plugin using the ``-c`` flag.

.. note::
   By default plugin-install assumes you want to install the plugin to be used 
   in QGIS2. To install the plugin for use in QGIS3, add the flag ``-v 3`` to 
   the ``plugin-install`` command. Remember the plugin may or may not work on 
   QGIS3 - the plugin was designed for QGIS2 and is still being tested on 
   QGIS3.

Modifying the Earth Engine processing code
__________________________________________


The Google Earth Engine (GEE) processing scripts used by Trends.Earth are all 
stored in the "gee" folder under the main trends.earth folder. For these script 
to be accessible to users of the trends.earth QGIS plugin, they have to be 
deployed to the api.trends.earth service Conservation International maintains 
in order to allow users of the plugin to use Earth Engine without the need to 
know how to program, or to have individual user accounts on GEE. The below 
describes how to test and deploy GEE scripts to be used with Trends.Earth.

Setting up dependencies
-----------------------

trends.earth-CLI
~~~~~~~~~~~~~~~~

The "trends.earth-CLI" Python package is required in order to work with the 
api.trends.earth server. This package is located on github in the 
`trends.earth-CLI <https://github.com/Vizzuality/trends.earth-CLI>`_ 
repository.

The first step is to clone this repository onto your machine. We recommend that 
you clone the repository into the same folder where you the trends.earth code. 
For example, if you had a "Code" folder on your machine, clone both the 
`trends.earth
<https://github.com/ConservationInternational/trends.earth>`_ repository (the 
code for the QGIS plugin and associated GEE scripts) and also the 
`trends.earth-CLI <https://github.com/Vizzuality/trends.earth-CLI>`_ repository 
into that same folder.

When you setup your system as recommended above, trends.earth-CLI will work 
with the invoke tasks used to manage trends.earth without any modifications. 
If, however, you download trends.earth-CLI into a different folder, then you 
will need to add a file named "invoke.yaml" file into the root of the 
trends.earth repository, and in that file tell Trends.Earth where to locate the 
trends.earth-CLI code. This YAML file should look something like the below (if 
you downloaded the code on Windows into a folder called 
"C:/Users/azvol/Code/trends.earth-CLI/tecli"):

.. code-block:: yaml

    gee:
        tecli: "C:/Users/azvol/Code/trends.earth-CLI/tecli"

Again, note that you do NOT need to add this .yaml file if you setup your 
system as recommended above.

docker
~~~~~~

The trends.earth-CLI package requires `docker <http://www.docker.com>`_ in 
order to function. `Follow these instructions to install docker on Windows 
<https://docs.docker.com/docker-for-windows/install/>`_, and `these 
instructions to install docker on Mac OS 
<https://docs.docker.com/docker-for-mac/install/>`_. If you are running
Linux, `follow the instructions on this page
<https://docs.docker.com/install>`_ that are appropriate for the Linux 
distribution you are using.

Testing an Earth Engine script locally
--------------------------------------

While converting a script specifying code to be run on GEE from JavaScript to 
Python, or when making modifications to that code, it can be useful to test the 
script locally, without deploying it to the api.trends.earth server. To do 
this, use the ``run`` invoke task. For example, to test the "land_cover" 
script, go to the root directory of the Trends.Earth code, and, in a command 
prompt, run::
   
   invoke tecli-run land_cover

This will use the trends.earth-CLI package to build and run a docker container 
that will attempt to run the "land_cover" script. If there are any syntax 
errors in the script, these will show up when the container is run. Before 
submitting a new script to api.trends.earth, always make sure that ``invoke 
tecli-run`` is able to run the script without any errors.

When using ``invoke tecli-run`` you may get an error saying:

.. code-block:: sh

   Invalid JWT: Token must be a short-lived token (60 minutes) and in a 
   reasonable timeframe. Check your iat and exp values and use a clock with 
   skew to account for clock differences between systems.
   
This error can be caused if the clock on the docker container gets out of sync 
with the system clock. Restarting docker should fix this error.

Deploying a GEE script to api.trends.earth
------------------------------------------

When you have finished testing a GEE script and would like it to be accessible 
using the QGIS plugin (and by other users of Trends.Earth), you can deploy it 
to the api.trends.earth server. The first step in the process is logging in to 
the api.trends.earth server. To login, run::
   
   invoke tecli-login

You will be asked for a username and password. These are the same as the 
username and password that you use to login to the Trends.Earth server from the 
QGIS plugin. Note that if you are not an adminstrator, you will be able to 
login, but the below command will fail. To upload a script (for example, the 
"land_cover" script) to the server, run::
   
   invoke tecli-publish land_cover

If this script already exists on the server, you will be asked if you want to 
overwrite the existing script. Be very careful uploading scripts with 
even-numbered versions, as these are publicly available scripts, and any errors
that you make will affect anyone using the plugin. Whenever you are testing be 
sure to use development version numbers (odd version numbers).

If you are making a new release of the plugin, and want to upload ALL of the 
GEE scripts at once (this is necessary whenenever the plugin version number 
changes), run::
   
   invoke tecli-publish

Again - never run the above on a publicly released version of the plugin unless 
you are intending to overwrite all the publicly available scripts used by the 
plugin.

Contributing to the documentation
_________________________________

Overview
--------

The documentation for Trends.Earth is produced using `Sphinx 
<http://www.sphinx-doc.org/en/master/>`_, and is written in `reStructuredText 
<http://docutils.sourceforge.net/rst.html>`_ format. If you are unfamiliar with 
either of these tools, see their documentation for more information on how they
are used.

The documentation for Trends.Earth is stored in the "docs" folder under the 
main trends.earth directory. Within that folder there are a number of key files
and folders to be aware of:

   + build: contains the build documenation for trends.earth (in PDF and HTML 
     format). Note it will only appear on your machine after running the 
     ``docs-build`` invoke task.
   + i18n: contains translations of the documenation into other languages. The 
     files in here are normally processed automatically using invoke tasks, so 
     you shouldn't ever have reason to modify anything in this folder.
   + resources: contains any resourcess (primarily images or PDFs) that are 
     referred to in the documentation.
   + source: contains the reStructuredText source files that define the 
     documentation (these are the actual English text of the documentation, and 
     are the files you are most likely to need to modify).


Installing dependencies
-----------------------

Python dependencies
~~~~~~~~~~~~~~~~~~~

In order to work with the documentation, you need to have invoke, Sphinx, 
sphinx-intl, and sphinx-rtd-theme (the theme for the Trends.Earth website) 
installed on your machine. These packages are all listed in the "dev" 
requirements file for Trends.Earth, so they can be installed by navigating in a 
command prompt to the root of the trends.earth code folder and typing::

   pip install -r requirements-dev.txt

LaTeX
~~~~~

LaTeX is used to produce PDF outputs of the documentation for Trends.Earth.

To install on Windows, `follow the process outlined here 
<https://www.tug.org/protext>`_ to install the proTeXt distribution of LaTeX 
from `the zipfile available here 
<http://ftp.math.purdue.edu/mirrors/ctan.org/systems/windows/protext/>`_. The 
LaTeX installer is quite large (several GB) so it might take some time to 
download and install.

On MacOS, MacTeX is a good option, and can be installed `following the 
instructions here <http://www.tug.org/mactex/>`_.

On Linux, installing LaTeX should be much easier - use your distribution's 
package manager to find and install whatever LaTeX distribution is included by 
default.

Updating and building the documentation
---------------------------------------

Once you have installed the sphinx requirements, you are ready to begin 
modifying the documentation. The files to modify are located under the 
"docs\source" folder. After making any changes to these files, you will need to 
build the documenation in order to view the results. There are two versions of 
the Trends.Earth documentation: an HTML version (used for the website) and a 
PDF version (for offline download). To build the documentation for 
Trends.Earth, use the "docs-build" invoke task. By default, this task will 
build the full documentation for Trends.Earth, in HTML and PDF, for all 
supported languages. This can take some time to run (up to a few hours). If you 
are just testing the results of some minor changes to the documentation, it is 
usually best to use the ``-f`` option (for "fast"). This
option will build only the English HTML documentation, which should take only a 
few seconds. To build using the fast option, run::

   invoke docs-build -f

The above command will take a few seconds to fun, and then if you look under 
"docs\build\html\en", you will see the HTML version of the documentation. Load 
the "index.html" file in a web browser to see how it looks.

To build the full documentation, for all languages, in PDF and in HTML 
(remember this could take a few hours to complete), run::

   invoke docs-build

After running the above command you will see (for English) the HTML 
documentation under "docs\build\html\en", and the PDFs of the documentation 
under "docs\build\html\en\pdfs".

If you want to test a specific language (when testing translations, for 
example), you can specify a two letter language code to only build the docs for 
that language. For example, to build the Spanish documentation only, run::

   invoke docs-build -l es


Note that options can be combined, so you can use the fast option to build only 
the HTML version of the Spanish documentation by running::

   invoke docs-build -f -l es

When building the full documentation for the website, it is a good idea to 
first remove any old builds of the documentation, as they might contain files 
that are no longer used in the updated documentation. To do this, use the 
``-c`` (clean) option::

   invoke docs-build -c

In general, docs-build MUST complete without any errors if you are planning to 
share the documentation or post it on the website. However, when testing things 
locally, you might want to ignore documentation errors that pop up only for 
some of the languages (due to syntax errors arising from translation errors, 
etc.), and continue building the remaining documentation regardless of whether 
there are any errors. To do this, use the ``-i`` (ignore errors) option::

   invoke docs-build -i

Whenever you make any changes to the text of the documentation, it is a good 
idea to push the latest strings to transifex so they can be translated. To 
update the strings on transifex with any new changes, run::

   invoke translate-push

Note that to successfully run the above command you will need to have the key 
for the Trends.Earth transifex account.

Building documentation for release
----------------------------------

Before releasing new documentation, always pull the latest translations from 
transifex so that all translations are up to date. To do this, run::

   invoke translate-pull

To build a version of the documentation for public release (either to the 
website, or in PDF) you must build the entire documentation using 
``docs-build`` with no additional parameters::

   invoke docs-build

This process must complete successfully with no errors. If any errors occur 
during the process, review the error message, and make any modifications needed 
to allow the build to complete successfully. Once the build completes with no 
errors, the files are ready to be deployed on the website.

Adding new documentation files
------------------------------

Any new .rst files that are added to the documentation need to be added to 
several configuration files to ensure they are properly translated, and (for 
tutorials) to ensure that they are generated in PDF so they can be downloaded 
for offline use.

.. todo:: add this

Files that need to be made available as separate PDFs (typically the tutorial 
sections of the documentation) also need to be listed in the 

.. todo:: add this

Contributing as a translator
----------------------------

.. todo:: add this
