# Trends.Earth 

[![Trends.Earth](https://s3.amazonaws.com/trends.earth/sharing/trends_earth_logo_bl_600width.png)](http://trends.earth)

[![Build 
Status](https://travis-ci.org/ConservationInternational/trends.earth.svg?branch=master)](https://travis-ci.org/ConservationInternational/trends.earth)

`Trends.Earth` (formerly the Land Degradation Monitoring Toolbox) is a tool for 
monitoring land change. `Trends.Earth` is a [QGIS](http://www.qgis.org) plugin 
that supports monitoring of land change, including changes in productivity, 
land cover, and soil organic carbon. The tool can support monitoring land 
degradation for reporting to the Global Environment Facility (GEF) and United 
Nations Convention to Combat Desertification (UNCCD), as well as tracking 
progress towards achivement of Sustainable Development Goal (SDG) target 15.3, 
Land Degradation Neutrality (LDN).

`Trends.Earth` was produced as an output of the GEF-funded project [“Enabling 
the use of global data sources to assess and monitor land degradation at 
multiple scales”](http://vitalsigns.org/gef-ldmp). The project aims to provide 
guidance on robust methods and a tool for assessing, monitoring status, and 
estimating trends in land degradation using remote sensing technology.

The Land Degradation Monitoring Project is a collaboration of Conservation
International, the National Aeronautics and Space Administration (NASA), and
Lund University.

## Documentation

See the [user guide](http://trends.earth/docs/en) for information on how to use 
the plugin.

## Installation

### Stable version (recommended)

The easiest way to install the plugin is from within QGIS, using the [QGIS 
plugin repository](http://plugins.qgis.org/plugins/LDMP/).

### Development version

If you are interested in using the very latest version of the plugin, or in 
contributing to the development of it, you will want to install the development 
version. There are two ways to install the development version:

* Using a packaged version (zipfile)

* Cloning the github repository and installing from that code

It is easier to install the plugin from a zipfile than from github, so this 
option is recommended unless you are interested in contributing to development 
of the plugin.

#### Installing the latest packaged version

Download [the latest `Trends.Earth` 
zipfile](https://s3.amazonaws.com/trends.earth/sharing/LDMP.zip).

Extract `LDMP.zip` to the python plugins folder for your installation of QGIS. 
For example, if you are using Windows and your username is "azvol", then this 
might be `C:\Users\azvol\.qgis2\python\plugins`. If you are using a Mac and 
your username is "azvol", then this might be
`/Users/azvol/.qgis2/python/plugins`.

Once you are finished, you should have a folder named "LDMP" within your 
`.qgis2/python/plugins` folder.

Start QGIS, and click on "Plugins" then "Manage and install plugins". In the 
plugins window that appears, click on "Installed", and then make sure there is 
a check in the box next to "Land Degradation Monitoring Tool". The plugin is 
now installed and activated. Click "Close", and start using the plugin.

#### Installing the very latest code from github

Open a terminal window and clone the latest version of the repository from 
Github:

```
git clone https://github.com/ConservationInternational/trends.earth
```

Navigate to the root folder of the newly cloned repository, and install 
`paver`, a tool that assists with installing the plugin:

```
pip install paver
```

Now run the setup task with `paver` to pull in the external dependencies needed 
for the project:

```
paver setup
```

Once `paver setup` has run, you can install the plugin using paver:

```
paver install
```

If you modify the code, you need to run `paver install` to update the installed 
plugin in QGIS. You only need to rerun `paver setup` if you change or update 
the plugin dependencies. After reinstalling the plugin you will need to restart 
QGIS or reload the plugin. Install the "Plugin reloader" plugin if you plan on 
making a log of changes (https://github.com/borysiasty/plugin_reloader).

## License

`Trends.Earth` is free and open-source. It is licensed under the GNU General 
Public License, version 2.0 or later.
