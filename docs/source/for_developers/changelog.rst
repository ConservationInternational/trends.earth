Changelog
======================

This page lists the version history of |trends.earth|.

`2.1.14 (February 24, 2023) <https://github.com/ConservationInternational/trends.earth/releases/tag/2.1.14>`_
-----------------------------------------------------------------------------------------------------------------------------

  - Improve land productivity import tool, including support for JRC,
    FAO-WOCAT, or Trends.Earth data, and option to specify initial and final
    years

`2.1.12 (February 17, 2023) <https://github.com/ConservationInternational/trends.earth/releases/tag/2.1.12>`_
-----------------------------------------------------------------------------------------------------------------------------

  - Improve data download tool, including support for downloading WorldPop
    population data used in UNCCD reporting

`2.1.10 (February 7, 2023) <https://github.com/ConservationInternational/trends.earth/releases/tag/2.1.10>`_
-----------------------------------------------------------------------------------------------------------------------------

  - Fix error when using shapefiles/geojsons to define aoi (#768)
  - Ensure user settings are retained and not reset by offline mode checks
  - Update translations

`2.1.8 (January 25, 2023) <https://github.com/ConservationInternational/trends.earth/releases/tag/2.1.8>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Output JSON field for Prais containing updated false positive/negative
      calculations.
    - Fixes #752 - false positive/negative datasets not showing up in
      non-English versions

`2.1.6 (December 8, 2022) <https://github.com/ConservationInternational/trends.earth/releases/tag/2.1.6>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Bumps maximum number of land cover classes to 45 (useful particularly for
      users seeking to use Corine legend)
    - Fix issue that was arising on Mac/Linux due to missing QgsPanelWidget ui
      file
    - Various more minor bug fixes

`2.1.6 (November 21, 2022) <https://github.com/ConservationInternational/trends.earth/releases/tag/2.1.6>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Fixes #691 (issue that arose if the base data directory was cleared).
      When base directory is cleared plugin will now reset the value to the
      default.
    - Fix python error coming up when settings window was closed while datasets
      screen was not open.

`2.1.2 (November 18, 2022) <https://github.com/ConservationInternational/trends.earth/releases/tag/2.1.2>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Fixes #724 - ensure max number of land cover classes is set to 38 by
      default (ignoring the previously set default value in qsettings, which
      used to be 32).
    - Fixes #722 - file name casing when code refers to
      land_cover_transition_matrix_unccd.json.
    - Fixes #726 - make dataset year visible in datasets window for imported
      datasets

`2.1.0 (November 11, 2022) <https://github.com/ConservationInternational/trends.earth/releases/tag/2.1.0>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Moved plugin settings to live within main QGIS plugin settings window
    - Bumped marshmallow-dataclass to 8.5.10 and marshmallow to 3.18.0. This
      necessitated changes in trends.earth-schemas, so it is possible some old
      jobs may not load in this new version (suggest re-running them if need
      be).

`2.0.7 (October 31, 2022) <https://github.com/ConservationInternational/trends.earth/releases/tag/2.0.7>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Enable Excel table generation for SDG 15.3.1 when using custom
      classes - all the various minor bugs should now be worked out.
    - Limit report generation to 3 tries - then quit trying to generate reports
      until next restart (prevents Trends.Earth continually spawing processes
      for report generation when they are failing).

`2.0.5 (October 19, 2022) <https://github.com/ConservationInternational/trends.earth/releases/tag/2.0.5>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Fix SDG summary generation when using JRC LPD or WOCAT LPD.

`2.0.3 (October 19, 2022) <https://github.com/ConservationInternational/trends.earth/releases/tag/2.0.3>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Allow bypassing reset of land cover legend when choosing defaults in
      the SDG tool.
    - Disable excel generation when child legend does not have 7 classes.
    - Fix report generation when using custom legend.

`2.0.1 (October 13, 2022) <https://github.com/ConservationInternational/trends.earth/releases/tag/2.0.1>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Added ability to completely customize the land cover legend used in
      Trends.Earth, including the number, name, color, and coding of each 
      class in the legend. This applies to all calculatons using land cover
      data, including the SDG 15.3.1 tool, and the productivity, soil organic
      carbon, and land cover indicator tools.
    - Reworked land cover import tool to allow importing data and assigning
      classes to custom legend.
    - Misc minor bug fixes.
    - Add ability to include false positive/negative dataset in UNCCD report.
      Next release will include further functionality to apply and report on
      false positive/negatives.
    - This experimental release disables the creation of Excel output tables
      for the SDG 15.3.1 tool. This functionality will be present in the next
      (stable) release.

`2.0 (July 20, 2022) <https://github.com/ConservationInternational/trends.earth/releases/tag/2.0>`_
-----------------------------------------------------------------------------------------------------------------------------

    - All new interface with simplified navigation screens and dataset loading
    - Updated documentation and website
    - Trends.Earth is now translated into all the official UN languages, as well as
      Portuguese. Swahili and Farsi translations (for the new interface) are planned as
      well.
    - New functions to support latest UNCCD reporting cycle (including direct support
      for exporting results for upload to UNCCD PRAIS system)
    - New functions to support assessing drought hazard, vulnerability, and
      exposure
    - New timeseries tool functions (now supports plotting restrend, WUE, etc.)

`1.0.10 (July 7, 2022) <https://github.com/ConservationInternational/trends.earth/releases/tag/1.0.10>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Address bug with TransformDirection related to changes in QGIS 3.22+

`1.0.8 (October 15, 2021) <https://github.com/ConservationInternational/trends.earth/releases/tag/1.0.8>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Address bug in saving final layer for SDG calculation (related to issues 
      #500, and #505)

`1.0.6 (July 15, 2021) <https://github.com/ConservationInternational/trends.earth/releases/tag/1.0.6>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Remove trends.earth-schemas as a submodule and install through setup.py 
      (much cleaner for version tracking, development, etc.)
    - Fix bug in loading 2020 NDVI data in GEE code (asset name wasn't set 
      right so 2020 wasn't loading)
    - Various invoke tasks added to help with plugin development/release.

`1.0.4 (June 30, 2021) <https://github.com/ConservationInternational/trends.earth/releases/tag/1.0.4>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Add WorldPop and Gridded Population of the World version 4 (GPWv4) to the 
      datasets available through Trends.Earth
    - Update to allow access to ESA-CCI land cover through 2020
    - Update GPCC and GPCP datasets
    - Fix bug when non-integer buffers are used
    - Minor documentation typo fixes

`1.0.2 (August 14, 2020) <https://github.com/ConservationInternational/trends.earth/releases/tag/1.0.2>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Fix urban area code to allow processing of AOIs with areas between 10,000 
      sq km and 25,000 sq km.
    - Add latest MERRA2 data (through 2019).
    - Remove maximum area limitation from download tool.
    - Bump httplib2 to 0.18.0.
    - Update from GPCC V6 to GPCC V7
    - Add 2019 Hansen et al. deforestation data
    - Update to latest colormap for degradation data (addressing issues with 
      reg/green colorblindness).
    - Add support for more datatypes in input shapefiles (add PointZ, 
      MultiPoint, MultiPointZ, PolygonZ, MultiPolygonZ).
    - Misc bugfixes to address Python errors that were coming up with some 
      QMessageBox messages.

`1.0.0 (April 27, 2020) <https://github.com/ConservationInternational/trends.earth/releases/tag/1.0.0>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Add ability to download and use pre-compiled binaries (compiled with 
      Numba) to speed up some local calculations. Right now this only is 
      available for the SDG15.3.1 summary table calculation, but eventually 
      this will be expanded to other tools as well.
    - Related to the above, there is now an "advanced" settings button in the 
      settings window, that will allow users to download pre-compiled binaries, 
      and to turn on or off detailed logging of messages while the tool is 
      running. These log messages can be useful when trying to trouble-shoot 
      problems if you encounter any.
    - Improve checks for geometry validity for geometries in input files, and 
      give an error message rather than throwing an exception when there are 
      geometry errors.
    - Fix processing using new MODIS data (assets were not properly updated in 
      the last release)
    - Fix color-coding of land covers in land cover class aggregation window
    - Add more detailed version information to about dialog.
    - Add additional detail to data download tool.
    - Add job ID to downloads window to facilitate bug reporting.
    - Minor bug fixes (sorting of jobs and downloads tables).

`0.98 (April 2, 2020) <https://github.com/ConservationInternational/trends.earth/releases/tag/0.98>`_
-----------------------------------------------------------------------------------------------------------------------------

    - First QGIS3 release - many fixes to upgrade to Qt5 and QGIS3 API.
    - Upgrade all dependencies of plugin to latest versions as of January 2020.
    - Fix data download tool to have default 1styles for all available 
      datasets.
    - Begin moving to QgsProcessing and QgsTask frameworks - currently only the 
      carbon tool is migrated, but all tools will be migrated prior to version 1.0./
    - Cleanup formatting of carbon tool output spreadsheet to make meaning of 
      each column clearer.
    - Update all GEE scripts to use latest version of GEE API (0.1.213).
    - Save more settings chosen in tool dialog boxes across QGIS sessions.
    - Clean up buffering code, to use Lambert Equal Area projections centered 
      on polygon centroids for buffering.
    - Move documentation into docs folder at root of trends.earth repository.
    - Add more details on how to documentation on how to contribute to 
      development of Trends.Earth,
    - Clean up repository by removing compiled translations files, and adding 
      these file types to .gitignore.
    - Change transifex project name to be "trendsearth".
    - Various compatibility and minor bug fixes.

`0.66 (July 20, 2019) <https://github.com/ConservationInternational/trends.earth/releases/tag/0.66>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Limit maximum area for tasks to 10,000,000 sq km, except for urban area 
      tasks, which is limited to 10,000 sq km.
    - Add background section on SDG 11.3.1, and update SDG 11.3.1 tutorial.
    - Update SDG 11.3.1 code to include 1998 in the series (internally during 
      calculation) in order to filter noise from the beginning of the urban series.
    - Fix date restrictions in SDG 15.3.1 all-in-one tool to account for both 
      ESA and MODIS availability.
    - Add section to readme on how to install Github releases.
    - Update and review Spanish translations, update google translations for 
      other languages.

`0.64 (July 9, 2019) <https://github.com/ConservationInternational/trends.earth/releases/tag/0.64>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Fix handling of nodata in total carbon tool.
    - Add support for 2018 Hansen data in total carbon tool.
    - Add support for global 30m biomass data from Wood's Hole in total carbon 
    - Set maximum final year for one step SDG 15.3.1 tool to be 2015 (matching 
      the ESA data).
    - Make Trends.Earth productivity the default dataset in SDG one step tool 
      for 15.3.1.

`0.62 (January 27, 2019) <https://github.com/ConservationInternational/trends.earth/releases/tag/0.62>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Add experimental tool for mapping potential carbon returns from 
      alternative restoration interventions.
    - Add 2018 MODIS data.
    - Miscellaneous fixes to window sizing for GUI windows.
    - Upgrade to latest openpyxl - fixes loading of Trends.Earth logo in 
      summary tables.
    - Add publication list to help docs.

`0.60 (December 3, 2018) <https://github.com/ConservationInternational/trends.earth/releases/tag/0.60>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Add calculation of change in urban area and population growth 
      rate (SDG 11.3.1)
    - Fix default button/entry field heights
      Add city selection for AOI
    - Add optional buffering of AOI

`0.58 (August 11, 2018) <https://github.com/ConservationInternational/trends.earth/releases/tag/0.58>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Add a testing section to the calculations page
    - Add testing version of total carbon (above and below-ground) and 
      emissions due to deforestation
    - Minor bug fixes, including for invalid polygons in input AOIs

`0.56.5 (May 21, 2018) <https://github.com/ConservationInternational/trends.earth/releases/tag/0.56.5>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Fix error with LPD import requesting a data year.

`0.56.4 (May 21, 2018) <https://github.com/ConservationInternational/trends.earth/releases/tag/0.56.4>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Always resample imported data to the highest resolution.
    - Fix custom SOC import climate zones to use an expanded climate zones 
      dataset to eliminate no data.
    - Update MOD16A2 with latest data.
    - Force entry of date on SOC and LC data import
    - Add global Trends.Earth outputs to download tool.
    - Fix handling of NULL values in legends.

`0.56.3 (April 21, 2018) <https://github.com/ConservationInternational/trends.earth/releases/tag/0.56.3>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Fix calculation of summary tables for AOIs that are split across the 
      180th meridian (Fiji, Russia, etc.).
    - Modify state calculation so areas with very small magnitude changes in 
      NDVI integral (< .01 NDVI units over full period) are considered stable.

`0.56.2 (April 10, 2018) <https://github.com/ConservationInternational/trends.earth/releases/tag/0.56.2>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Minor unicode fixes.

`0.56.1 (April 10, 2018) <https://github.com/ConservationInternational/trends.earth/releases/tag/0.56.1>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Fix marshhmallow error on plugin load

`0.56 (April 9, 2018) <https://github.com/ConservationInternational/trends.earth/releases/tag/0.56>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Fix issue with rasterizing data (empty rasters on output)
    - Force user to choose output resolution if rasterizing a vector
    - Support calculation of SOC degradation from custom SOC and LC data

`0.54 (April 8, 2018) <https://github.com/ConservationInternational/trends.earth/releases/tag/0.54>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Support loading of custom LPD, SOC, and LC data.
    - Cleanup styles so they match maps.trends.earth
    - Upgrade pyopenxl
    - Add import/load icons to all layer selector boxes

`0.52.1 (March 21, 2018) <https://github.com/ConservationInternational/trends.earth/releases/tag/0.52.1>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Minor bug fixes during Antalya workshop.

`0.52.1 (March 21, 2018) <https://github.com/ConservationInternational/trends.earth/releases/tag/0.52.1>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Minor bug fixes during Antalya workshop.

`0.52 (March 19, 2018) <https://github.com/ConservationInternational/trends.earth/releases/tag/0.52>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Clean AOI processing code.

`0.50 (March 15, 2018) <https://github.com/ConservationInternational/trends.earth/releases/tag/0.50>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Pass exception if only related to Trends.Earth logo addition in Excel 
      file.
    - Various minor bug fixes.

`0.48 (March 13, 2018) <https://github.com/ConservationInternational/trends.earth/releases/tag/0.48>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Fix table formatting

`0.46 (March 13, 2018) <https://github.com/ConservationInternational/trends.earth/releases/tag/0.46>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Support reporting table calculation with multiple geometries (Fiji, Russia)
    - Add LPD and LC tables to UNCCD worksheet tab
    - Clean up the warning message in the LPD import tool
    - Fix TE final combined productivity layer loading
    - Fix download tasks (still no styles)

`0.44 (March 12, 2018) <https://github.com/ConservationInternational/trends.earth/releases/tag/0.44>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Add JRC LPD
    - Add tool for uploading custom land cover data
    - Add tool for uploading custom productivity data
    - Add note that custom SOC upload is coming soon
    - Add tool to add basemaps using Natural Earth data
    - Add all-in-one tool for calculating all three sub-indicators at once
    - Rename "Bare lands" class to "Other lands" for consistency with UNCCD
    - Update docs
    - Upgrade to marshmallow 3.0.0b7
    - Move GEE code into the main trends.earth repository
    - Improve handling of AOIs, particularly when shapefiles are used for input
    - Handle multi-file outputs from GEE by tiling them in VRTs
    - Support processing data for countries that cross the 180th meridian
    - Improve formatting of summary table
    - From now on, GEE script versions will be matched to the plugin version

`0.42 (February 4, 2018) <https://github.com/ConservationInternational/trends.earth/releases/tag/0.42>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Fix crash on change of LC aggregation (due setEnabled on removed label)

`0.40 (February 4, 2018) <https://github.com/ConservationInternational/trends.earth/releases/tag/0.40>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Remove use of mode for land cover indicator.
    - Combine the summary table and SDG indicator map creation tools.
    - Add stub for where JRC LPD product will be available.
    - Save productivity sub-indicator as band 2 in SDG indicator file.
    - Bump GEE script to v0.3.
    - Fix error due to divide by zero on summary table generation when a class 
      has zero area.
    - Default to MODIS for productivity calculations.

`0.38 (January 16, 2018) <https://github.com/ConservationInternational/trends.earth/releases/tag/0.38>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Add annual soil organic carbon calculation
    - Cleanup AOI processing code, allow multiple input polygons in shapefile 
      AOIs
    - Add shading to side of land cover aggregation table items
    - Fix firstShow issue on aggregation table
    - Revise summary table output to provide further information on each of the 
      three indicators
    - Add supplemental datasets to performance, state, land cover and soil 
      organic carbon output.
    - Update no data and masking values to consistently be -32768 (no data) and 
      -32767 (masked data)
    - Allow naming of file downloads
    - Add icon to toolbar menu, fix plugin name.
    - Refactor layer styling code to pull band info from GEE output.
    - Add a tool to load existing trends.earth datasets into QGIS.
    - Fix land cover date limits - don't allow invalid dates toi be selected 
      from CCI data.

`0.36 (December 14, 2017) <https://github.com/ConservationInternational/trends.earth/releases/tag/0.36>`_
-----------------------------------------------------------------------------------------------------------------------------

    - Fix issue with showEvent on create map reporting tool.

`0.34 (December 14, 2017) <https://github.com/ConservationInternational/trends.earth/releases/tag/0.34>`_
-----------------------------------------------------------------------------------------------------------------------------


`0.32 (December 14, 2017) <https://github.com/ConservationInternational/trends.earth/releases/tag/0.32>`_
-----------------------------------------------------------------------------------------------------------------------------


`0.30 (December 12, 2017) <https://github.com/ConservationInternational/trends.earth/releases/tag/0.30>`_
-----------------------------------------------------------------------------------------------------------------------------


`0.24 (December 6, 2017) <https://github.com/ConservationInternational/trends.earth/releases/tag/0.24>`_
-----------------------------------------------------------------------------------------------------------------------------


`0.22 (December 4, 2017) <https://github.com/ConservationInternational/trends.earth/releases/tag/0.22>`_
-----------------------------------------------------------------------------------------------------------------------------


`0.18 (December 2, 2017) <https://github.com/ConservationInternational/trends.earth/releases/tag/0.18>`_
-----------------------------------------------------------------------------------------------------------------------------


`0.16 (November 6, 2017) <https://github.com/ConservationInternational/trends.earth/releases/tag/0.16>`_
-----------------------------------------------------------------------------------------------------------------------------


`0.14 (October 25, 2017) <https://github.com/ConservationInternational/trends.earth/releases/tag/0.14>`_
-----------------------------------------------------------------------------------------------------------------------------


`0.12 (October 6, 2017) <https://github.com/ConservationInternational/trends.earth/releases/tag/0.12>`_
-----------------------------------------------------------------------------------------------------------------------------

