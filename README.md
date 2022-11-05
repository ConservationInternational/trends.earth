# Trends.Earth

[![Trends.Earth](https://s3.amazonaws.com/trends.earth/sharing/trends_earth_logo_bl_600width.png)](http://trends.earth)

[![Documentation Status](https://readthedocs.org/projects/trendsearth/badge/?version=latest)](https://trendsearth.readthedocs.io/en/latest/?badge=latest)
[![Zipfile Status](https://github.com/ConservationInternational/trends.earth/actions/workflows/build_zipfile.yaml/badge.svg)](https://github.com/ConservationInternational/trends.earth/actions/workflows/build_zipfile.yaml)
[![Update translations](https://github.com/ConservationInternational/trends.earth/actions/workflows/translation_update.yaml/badge.svg)](https://github.com/ConservationInternational/trends.earth/actions/workflows/translation_update.yaml)
[![Tests](https://github.com/ConservationInternational/trends.earth/actions/workflows/test.yaml/badge.svg)](https://github.com/ConservationInternational/trends.earth/actions/workflows/test.yaml)

`Trends.Earth` is a free and open source tool to understand land change: the how and why
behind changes on the ground. Trends.Earth allows users to draw on the best available
information from across a range of sources - from globally available data to customized
local maps. A broad range of users are applying Trends.Earth for projects ranging from
planning and monitoring restoration efforts, to tracking urbanization, to developing
official national reports for submission to the United Nations Convention to Combat
Desertification (UNCCD).

`Trends.Earth` is a [QGIS](http://www.qgis.org) plugin that supports monitoring of land
change, including trends in urbanization, and changes in productivity, land cover, and
soil organic carbon. The tool can support monitoring land degradation for reporting to
the Global Environment Facility (GEF) and United Nations Convention to Combat
Desertification (UNCCD), as well as tracking progress towards achievement of Sustainable
Development Goal (SDG) target 15.3, Land Degradation Neutrality (LDN).

`Trends.Earth` was produced by a partnership of Conservation International, Lund
University, and the National Aeronautics and Space Administration (NASA), with
the support of the Global Environment Facility (GEF). It was further developed
through a partnership with Conservation International, University of Bern,
University of Colorado in partnership with USDA and USAID, University of California -
Santa Barbara in partnership with University of North Carolina - Wilmington and Brown
University with additional funding from the Global Environment Facility (GEF).

## Documentation

See the [user guide](http://trends.earth) for information on how to use
the plugin.

## Installation of stable version of plugin

The easiest way to install the plugin is from within QGIS, using the [QGIS
plugin repository](http://plugins.qgis.org/plugins/LDMP/). However, It is also
possible to install the plugin manually from a zipfile, which can be useful to
access an old version of the plugin, or to install the plugin without internet.
Instructions for both of these possibilities are below.

### Stable version from within QGIS (recommended)

The easiest way to install the plugin is from within QGIS, using the [QGIS
plugin repository](http://plugins.qgis.org/plugins/LDMP/).

### Stable version from zipfile

Download a stable version of `Trends.Earth` from
[the list of available releases on
GitHub](https://github.com/ConservationInternational/trends.earth/releases). Then follow
the instructions below on [installing the plugin from a
zipfile](#installing-plugin-from-a-zipfile).

## Installation of unstable version of plugin

If you are interested in using the unstable (actively under development) version of the
plugin, with the very latest (but not as well tested) features, or in contributing to
the development of it, you will want to install the development version. There are
two ways to install the development version:

- Using a packaged version (zipfile)

- Cloning the github repository and installing from that code

It is easier to install the plugin from a zipfile than from github, so this
option is recommended unless you are interested in contributing to development
of the plugin.

### Development version from zipfile

[Download the latest `Trends.Earth` zipfile](https://s3.amazonaws.com/trends.earth/sharing/LDMP_main.zip) (or use the
[the zipfile from the develop branch
](https://s3.amazonaws.com/trends.earth/sharing/LDMP_develop.zip) for the absolute
latest version). Then follow the instructions below on [installing the plugin
from a zipfile](#installing-plugin-from-a-zipfile).

QGIS3+ is required for the latest versions of Trends.Earth. The QGIS2 version is no
longer supported (support ended in March 2020). If you want to use a previous version of
`Trends.Earth` (e.g. versions that work with QGIS2), please refer to this
[repository](https://github.com/ConservationInternational/trends.earth/releases) where
all `Trends.Earth` releases are available.

### Development version from source

Open a terminal window and clone the latest version of the repository from
Github:

```
git clone https://github.com/ConservationInternational/trends.earth
```

Navigate to the root folder of the newly cloned repository, and install
`invoke`, a tool that assists with installing the plugin:

```
pip install invoke
```

Now run the setup task with `invoke` to pull in the external dependencies needed
for the project:

```
invoke plugin-setup
```

then you can install the plugin using invoke:

```
invoke plugin-install --profile=<profile name>
```

If you modify the code, you need to run `invoke plugin-install` to update the
installed plugin in QGIS. You only need to rerun `invoke plugin-setup` if you
change or update the plugin dependencies. After reinstalling the plugin you
will need to restart QGIS or reload the plugin. Install the "Plugin reloader"
plugin if you plan on making a log of changes
(https://github.com/borysiasty/plugin_reloader).

## Installing plugin from a zipfile

While installing `trends.earth` directly from within QGIS is recommended, it
might be necessary to install the plugin from a zipfile if you need to install
it offline, or if you need the latest features.

To install from a zipfile, first download a zipfile of the
[stable](#stable-version-from-zipfile) or
[development](#development-version-from-zipfile) version. The zipfile might be
named `LDMP.zip`or `LDMP_QGIS3.zip` depending on what
version you are installing.

When using QGIS3.10.3 or greater versions it is possible to install `trends.earth`
directly from a zipfile. To install `trends.earth` from a zipfile, open QGIS3.10.3
(or greater) and click on "Plugins" then on "Manage and install plugins" and
choose the option "Install from ZIP". Browse to the folder in which the zipfile
has been saved, select the zipfile and click on 'Install Plugin'.
It is not necessary to unzip the file.

Please, note that the latest version of `trends.earth` is only supported for
QGIS3.10.3 or greater versions.

Start QGIS, and click on "Plugins" then "Manage and install plugins". In the
plugins window that appears, click on "Installed", and then make sure there is
a check in the box next to "Land Degradation Monitoring Tool". The plugin is
now installed and activated. Click "Close", and start using the plugin.

## Getting help

### General questions

If you have questions related to the methods used by the plugin, how to use a
particular dataset or function, etc., it is best to first check the [user
guide](http://trends.earth/docs/en) to see if your question is already
addressed there. The [frequently asked questions (FAQ)
page](http://trends.earth/docs/en/about/faq.html) is another good place to
look.

If you don't find your answer in the above pages, you can also [contact the
discussion group](https://groups.google.com/forum/#!forum/trends_earth_users).

### Reporting an issue (error, possible bug, etc.)

If you think you have found a bug in Trends.Earth, report your issue to our
[issue
tracker](https://github.com/ConservationInternational/trends.earth/issues) so
the developers can look into it.

When you report an issue, be sure to provide enough information to allow us to
be able to reproduce it. In particular, be sure to specify:

- What you were doing with the plugin when the problem or error ocurred (for
  example "I clicked on 'Download Results' and got an error messaging saying
  `describe what the message said`".
- The operating system you are using, version of the plugin are you using, and
  version of QGIS that you are using
- If you are emailing about an error or problem that occurred when downloading
  results, tell us your username, and the task start time that is listed in the
  download tool for the task you are referring to
- If the error occurred while processing data with the plugin, tell us the
  location you were analyzing with the tool (for example: "I selected Argentina
  from the dropdown menu"). If you used your own shapefile, please send us the
  file you used.
- If you got a message saying "An error has ocurred while executing Python
  code", send us either the text of the message, or a a screenshot of the error
  message. **Also, send us the content of the Trends.Earth log messages
  panel.** To access the Trends.Earth log messages panel, select "View", then
  "Panels", then "Log Messages" from within QGIS. Copy and paste the text from
  that panel and include it in your issue report. It will make it easiest for
  us to track things down (as their will be fewer log messages) if you do this
  after first starting a new QGIS session and immediately reproducing the
  error.

## License

`Trends.Earth` is free and open-source. It is licensed under the GNU General
Public License, version 2.0 or later
