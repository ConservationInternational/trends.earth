.. _tut_land_degradation:

Land Degradation
===================

Land Degradation Subindicators
--------------------------------

- **Objective**: Learn how to run SDG 15.3.1 sub-indicators (changes in land productivity, land cover and soil organic carbon) using Trends.Earth and the default data: Trends.Earth (trajectory, performance and state) for land productivity, ESA CCI for land cover, and SoilGrids for soil organic carbon. In this tutorial we will use Uganda as an example, but you can choose any study area.

- **Estimated time of completion**: 35 minutes

- **Internet access**: Required

1. Click on the Trends.Earth toolbar within QGIS, and click on the Trends.Earth icon.
   
.. image:: ../../../resources/en/common/icon-trends_earth_selection.png
   :align: center   

2. The **Trends.Earth** menu will open. In the **Algorithm** window, click on SDG 15.3.1 - Land degradation

.. image:: ../../../resources/en/documentation/calculate/all_sub-indicators_at_once.png
   :align: center

Select **Execute remotely** button for the Sub-indicators for SDG 15.3.1 analysis.

3. In the **SDG 15.3.1 Indicator (one-step) Land Degradation** window. Select the **Trends.Earth land productivity** data.  

4. Select the check box next to **Include progress period (for comparison to baseline)**

.. image:: ../../../resources/en/training/t03/all_subindicators.png
   :align: center

5. Type in the Execution name and notes.

6. Select **Schedule remote execution**

.. note::
    Refer to the :ref:`background_landdegradation` section of this manual to learn about the Trends.Earth productivity indicators developed following the `UNCCD Good Practice Guidance (GPG) <https://www.unccd.int/sites/default/files/relevant-links/2021-03/Indicator_15.3.1_GPG_v2_29Mar_Advanced-version.pdf>`_.
   
11. A light blue bar will temporarily show, indicating that the task was successfully submitted. The analysis will be run in Google servers and could take between 5 and 15 minutes depending on the size of the study area (larger areas tend to take longer).

.. image:: ../../../resources/en/training/t03/submitted.png
   :align: center   

.. _training_final_ldindicator:

Calculate SDG 15.3.1 Indicator and UNCCD's SO 2-3
-------------------------------------------------

- **Objective**: Learn to integrate the land cover, primary productivity and soil organic carbon sub-indicators to compute SDG 15.3.1 in raster format and tabular outputs with areas estimated.

- **Estimated time of completion**: 20 minutes

- **Internet access**: Not required

.. note::
    You will need to have previously computed the sub-indicators prior to running this tool. If you have not, please refer to the following specific tutorials to compute them: :ref:`tut_land_degradation`, :ref:`tut_custom_lc`, :ref:`tut_custom_lpd`, and :ref:`tut_custom_soc`.

1. Search for the Trends.Earth toolbar within QGIS, and click on the Trends.Earth icon.
   
.. image:: ../../../resources/en/common/icon-trends_earth_selection.png
   :align: center   

2. The **Trends.Earth** panel will open. In the **Algorithm** window, click on **SDG 15.3.1- Land Degradation** and select **Execute locally** under **Indicator for SDG 15.3.1**.

.. image:: ../../../resources/en/documentation/calculate/so1_sdg1531_indicator.PNG
   :align: center

.. image:: ../../../resources/en/common/execute-locally.png
   :align: center
   
The region of interest is already set up in Settings. If you need to change, select the **Change region** button.

.. note::
    Refer to the :ref:`tut_settings` section of this manual for more information on setting up your area of interest.
	
Select the datasets from **Baseline dataset** and **Progress dataset** dropdowns according to your selections in the sub-indicator analysis.

.. image:: ../../../resources/en/training/t03/final_subindicator.png
   :align: center
   
If you have the sub-indicators loaded into the QGIS map, the tool will recognize them and they will show up pre-filled in each corresponding section.

.. note::
	If you have more than one layer loaded into the map per sub-indicator (for example, land cover change computed with default and also with custom data) make sure to check that the one being used to compute the final SDG is the one you want.

3. Click on **Advanced** to expand it and show advanced options then select the **Population (required to calculate populations exposed by degradation** check box to calculate UNCCD's SO 2-3. 
|trends.earth| provides access the WorldPop dataset, which is used by default by the UNCCD for calculating indicator SO2-3. 

.. image:: ../../../resources/en/documentation/calculate/so2_ld_pop_exposure.PNG
   :align: center
   

4. When the analysis is completed a **Success** message will notify you and the indicator will be loaded to the map.   
 
5. In the **Datasets** window, click on click on **Load dataset onto QGIS map area**

.. image:: ../../../resources/en/training/t05/sdg_add_indicator_dataset.png
   :align: center

.. image:: ../../../resources/en/training/t05/sdg_indicator.png
   :align: center
   
.. note::
    Refer to the :ref:`background_landdegradation` background for interpreting the results of this analysis.

Land Degradation Summary
--------------------------------

- **Objective**: Learn how to open and interpret the summary tables produced by Trends.Earth when calculating the final SDG 15.3.1 layer.

- **Estimated time of completion**: 25 minutes

- **Internet access**: Not required

.. note:: `Download this page as a PDF for offline use 
   <../pdfs/Trends.Earth_Tutorial08_The_Summary_Table.pdf>`_

.. note::
    You will need to have previously computed SDG 15.3.1 using the **Indicator for SDG 15.3.1** tool. Refer to the section :ref:`training_final_ldindicator` for instructions on how to run this analysis.

1. When you calculate Indicator for SDG 15.3.1 an Excel file is created with the summary table. In the **Datasets** window, click on click on **Open Dataset Directory**

.. image:: ../../../resources/en/training/t05/sdg_open_dataset_directory.png
   :align: center

The directoty where the summary table was saved along with the geospatial data will open. You see two summary tables in case both Baseline and Progress SDG 15.3.1 were calculated

.. image:: ../../../resources/en/training/t06/sdg_find_table.png
   :align: center

2. The summary table file contains 6 tabs, which you can explore by clicking on each of the different names the bottom of the screen: SDG 15.3.1, Productivity, Soil organic carbon, Land Cover, Population and UNCCD SO1-1.   

3. In the **SDG 15.3.1** tab you will find the area calculations derived from the indicator map you explored in QGIS.

 For the area you run the analysis, you will see the total land area (excluding water bodies): land that experienced improvement, which remained stable, areas degraded, and also information on the areas with no data for the period selected. No data in the SDG 15.3.1 is an indication of no data in some of the input datasets used in the analysis.

.. image:: ../../../resources/en/training/t06/table_sdg.png
   :align: center

3. In the **Productivity** tab you will find at the top, a similar summary as previously explained, but in this case representing the results of the land productivity sub-indicator alone.

 In the sections below you will find two tables, each containing area information (in sq. km) for each of the land cover transitions found in the study are during the period analyzed broken by each of the 5 final land productivity classes: Increasing, Stable, Stable but stressed, Early signs of decline, and Declining.
   
.. image:: ../../../resources/en/training/t06/table_productivity.png
   :align: center

4. In the **Soil organic carbon** tab you will find at the top, a similar summary as previously explained, but in this case representing the results of the soil organic carbon sub-indicator alone.   

 In the sections below you will find two tables:
 
 - The first one contains information on changes in carbon stocks from the baseline (initial year of analysis) to the target (final year of analysis).
 - The second presents information soil organic carbon change from baseline to target by type of land cover transition (as percentage of initial stock).

.. image:: ../../../resources/en/training/t06/table_soc.png
   :align: center
   
5. In the **Land cover** tab you will find at the top, a similar summary as previously explained, but in this case representing the results of the land cover change sub-indicator alone.      
   
 In the sections below you will find two tables:
 
 - The first contains information on land cover change by cover class (sq, km and %).
 - The second contains information on land area by type of land cover transition (sq. km).
   
.. image:: ../../../resources/en/training/t06/table_landcover.png
   :align: center
   
6. In the **Population** tab you will find a summary of population affected by land degradation classes, with absolute and percent values reported.      
     
.. image:: ../../../resources/en/training/t06/table_population.png
   :align: center

7. In the **UNCCD SO1-1** tab you will find five tables containing similar information as the one presented in the previous tabs, but in this case specifically formatted to match the reporting template required by the UNCCD. Each table indicates at the top the page number and section of the template the information is referring to.
   
.. image:: ../../../resources/en/training/t06/table_unccd.png
   :align: center

.. note::
    Refer to the :ref:`indicator-productivity` to learn more on land productivity.

.. _tut_custom_lpd:
   
Custom Data - Productivity
--------------------------------
- **Objective**: Learn how to load custom land productivity data computed outside of Trends.Earth.

- **Estimated time of completion**: 20 minutes

- **Internet access**: Not required

Land productivity data should be formatted following UNCCD guidelines for reporting indicating areas of Declining, Moderate decline, Stressed, Stable, or Increasing land productivity.
   
For the productivity data to be used in Trends.Earth the file need to be coded in the following way:
 - Declining = 1
 - Moderate decline = 2
 - Stressed = 3
 - Stable = 4
 - Increasing = 5
 - No data = 0 or -32768

 If your layer is not coded in such a way, please do the necessary adjustments/reclassification prior to using Trends.Earth.
 
1. To load a custom productivity data click on the **Datasets** window, and then click on **Import datset**.

.. image:: ../../../resources/en/common/trends_earth_import_dataset.png
   :align: center

2. Several options will appear. Select **Import custom Productivity dataset** from the list.

.. image:: ../../../resources/en/training/t10/import_custom_lp.png
   :align: center

3. In the **Load a Custom Land Productivity Dataset** use the radio button to select the format of the input file (raster or vector). For this tutorial select raster, since the data distributed by the UNCCD is in raster format. Click on **Browse** to navigate to the productivity file you wish to import.

.. image:: ../../../resources/en/training/t10/import_custom_lp_2.png
   :align: center


4. In the **Load a Custom Land Productivity Dataset** window you also have options for selecting the band number in which the productivity data is stored, in case your input file is a multi band raster. You also have the option of modifying the resolution of the file. We recommend leaving those as defaults unless you have valid reasons for changing them.


5. Click **Browse** at the bottom of the window to select the **Output raster file** and navigate to the folder where you want to save the file. Assign it a name and click **OK**.
   

6. Back at the **Load a Custom Land Productivity Dataset** window click **OK** on the lower right corner to process the data.
   
7. If the values of the input file do not exactly match the requirements describe above, you will see a warning message. In many cases the warning is triggered by the definition of NoData, but the tool will still try to import it. For that reason, it is **extremely important** for you to explore the output layer to make sure the results are mapped as expected.

.. image:: ../../../resources/en/training/t10/warning.png
   :align: center

8. Once you click **Execute remotelly** a progress bar will appear showing the percentage of the task completed.
   
.. image:: ../../../resources/en/training/t10/import_custom_lp_ribon.png
   :align: center 

9. In the **Datasets** window, find the **Imported dataset (land productivity) and click on click on **Load dataset onto QGIS map area**.   
   
.. image:: ../../../resources/en/training/t10/import_custom_lp_add_dataset.png
   :align: center
   
.. note::
    Refer to the :ref:`indicator-land-cover` to learn more on land cover.
   
.. _tut_custom_lc:

Custom Data - Land Cover
--------------------------------
 **Objective**: Learn how to load custom land cover data and to compute the land cover change sub-indicator using Trends.Earth.

- **Estimated time of completion**: 40 minutes

- **Internet access**: Not required

.. note:: The land cover dataset for this tutorial were provided by the 
   `Regional Centre For Mapping Resource For Development 
   <http://geoportal.rcmrd.org/layers/servir%3Auganda_landcover_2014_scheme_i>`_ 
   and can be downloaded from this `link <https://s3.amazonaws.com/trends.earth/sharing/RCMRD_Uganda_Land_Cover.zip>`_.
   

1. To load a custom productivity data click on the **Datasets** window, and then click on **Import datset**.

.. image:: ../../../resources/en/common/trends_earth_import_dataset.png
   :align: center

2. Several options will appear. Select **Import custom Land Cover dataset** from the list.

.. image:: ../../../resources/en/training/t10/import_custom_lc.png
   :align: center

3. In the **Load a Custom Land Cover Dataset** window, use the radio button to select the format of the input file (raster or vector). For this tutorial select raster, since the data distributed by the UNCCD is in raster format. Click on **Browse** to navigate to the land cover file you wish to import.
   
.. image:: ../../../resources/en/training/t10/import_custom_lc_2.png
   :align: center

4. In the **Load a Custom Land Cover Dataset** window you also have options for selecting the band number in which the land cover data is stored, in case your input file is a multi band raster. You also have the option of modifying the resolution of the file. We recommend leaving those as defaults unless you have valid reasons for changing them.

   Define the year of reference for the data. In this case, since the land cover dataset for Uganda was developed for the **year 2000**, define it as such. Make sure you are assigning the correct year.
  
5. Click on the **Edit definition** button, this will open the **Setup aggregation of land cover data menu**. Here you need to assign each of the original input values of your dataset to one of the 7 UNCCD recommended land cover classes. 

.. image:: ../../../resources/en/training/t08/definition1.png
   :align: center

For this example, the Uganda dataset has 18 land cover classes:
   
.. image:: ../../../resources/en/training/t08/uganda_legend.png
   :align: center

From the Metadata of the land cover dataset, we know that the best aggregation approach is the following:   
 - No data = 0
 - Tree covered = 1 through 7
 - Grassland = 8 through 11
 - Cropland = 12 through 14
 - Wetland = 15
 - Water body = 16
 - Artificial = 17
 - Other land = 18

6. Use the **Setup aggregation of land cover data menu** to assign to each number in the **Input class** its corresponding **Output class**.

 When you are done editing, click **Save definition file**. This option will save you time next time you run the tool, by simply loading the definition file you previously saved.

 Click **Save** to continue 
 
.. image:: ../../../resources/en/training/t08/lc_definition.png
   :align: center

7. Back at the **Load a Custom Land Cover dataset** window, click **Browse** at the bottom of the window to select the **Output raster file** and navigate to the folder where you want to save the file. Assign it a name and click **OK**. 
   
.. image:: ../../../resources/en/training/t10/import_custom_lc_3.png
   :align: center

8. A progress bar will appear showing the percentage of the task completed.      
   
.. image:: ../../../resources/en/training/t08/running.png
   :align: center

9. When the processing is completed, the imported land cover dataset will be loaded to QGIS.   
   
.. image:: ../../../resources/en/training/t08/lc_loaded.png
   :align: center

.. note:: You have one imported custom land cover data for one year (2000), but two are needed to perform the land cover change analysis. Repeat now steps 1 through 8, but this time with the most recent land cover map. For this tutorial, we will use another land cover map from Uganda from the year 2015. **Make sure to change the year date in the import menu**.

10. Once you have imported the land cover maps for years 2000 and 2015, you should have them both loaded to QGIS.

.. image:: ../../../resources/en/training/t08/both_lc_loaded.png
   :align: center

11. Now that both land cover datasets have been imported into Trends.Earth, the land cover change analysis tool needs to be run. Search for the Trends.Earth toolbar within QGIS, and click on the Calculate icon (|iconCalculator|).
   
.. image:: ../../../resources/en/training/t08/trends_earth_calculate_custom_land_cover.PNG
   :align: center   
   
.. image:: ../../../resources/en/training/t08/call_lc_change_locally.png
   :align: center     

12. The **Land Cover | Land Degradation** window will open. Use the drop down option next to **Initial year layer** and **Target year layer** to change the dates accordingly.
   
.. image:: ../../../resources/en/training/t08/call_lc_change_tool.png
   :align: center 
   
The region of interest is already set up in Settings. If you need to change, select the **Change region** button.

.. note::
    Refer to the :ref:`tut_settings` section of this manual for more information on setting up your area of interest.

13. Click on **Advanced** to expand it. Here you will define the meaning of each land cover transition in terms of degradation. Transitions indicated in purple (minus sign) will be identified as degradation in the final output, transitions in beige (zero) will be identified as stable, and transitions in green (plus sign) will be identified as improvements. 

 For example, by default it is considered that a pixel that changed from **Grassland** to **Tree-covered** will be considered as improved. However, if in your study area woody plant encroachment is a degradation process, that transition should be changed for that particular study area to degradation (minus sign).

 If you have made no changes to the default matrix, simply click **Execute locally**.

 If you did change the meaning of some of the transitions, click on **Save table to file...** to save the definition for later use.   
   
.. image:: ../../../resources/en/training/t08/lc_degradation_matrix.png
   :align: center 
   
19. When you click **Execute locally**,a progress bar will appear showing the percentage of the task completed.     
   
.. image:: ../../../resources/en/training/t08/call_lc_change_ribon.png
   :align: center    

9. In the **Datasets** window, find the **Imported dataset (land productivity) and click on click on **Load dataset onto QGIS map area**.   
   
.. image:: ../../../resources/en/training/t08/import_custom_lc_add_dataset.png
   :align: center
   
.. _tut_custom_soc:

Custom Data - SOC
--------------------------------

- **Objective**: Learn how to load custom soil organic carbon data to compute the carbon change sub-indicator using Trends.Earth.

- **Estimated time of completion**: 20 minutes

- **Internet access**: Not required

.. _load_custom_soc:

Loading custom soil organic carbon data
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. note:: This tool assumes that the units of the raster layer to be imported are **Metrics Tons of organic carbon per hectare**. If your layer is in different units, please make the necessary conversions before using it in Trends.Earth.

1. To load soil organic carbon data click on the (|iconfolder|) icon in the Trends.Earth toolbar.

.. image:: ../../../resources/en/common/ldmt_toolbar_highlight_loaddata.png
   :align: center

2. The **Load data** menu will open. Select **Soil organic carbon** from the **Import a custom input dataset** section.
   
.. image:: ../../../resources/en/training/t09/custom_soc.png
   :align: center

3. In the **Load a Custom Soil Organic Carbon (SOC) dataset** use the radio 
   button to select the format of the input file (raster or vector). For this 
   tutorial select raster, since the data distributed by the UNCCD is in raster 
   format. Click on **Browse** to navigate to the soil organic carbon file you 
   wish to import.
   
.. image:: ../../../resources/en/training/t09/custom_soc_menu1.png
   :align: center

4. Use the **Select input file** window to navigate to the file to be imported, select it, and click **Open**.   
   
.. image:: ../../../resources/en/training/t09/soc_input.png
   :align: center

5. Back at the **Load a Custom Soil Organic Carbon (SOC) dataset** window you have options for selecting the band number in which the productivity data is stored, in case your input file is a multi band raster. You also have the option of modifying the resolution of the file. We recommend leaving those as defaults unless you have valid reasons for changing them.

6. Define the year of reference for the data. In this case, we will assume the soil organic carbon data is from 2000, but if using local data, make sure you are assigning the correct year.

7. Click **Browse** at the bottom of the window to select the **Output raster file**.
   
.. image:: ../../../resources/en/training/t09/custom_soc_menu2.png
   :align: center

8. Navigate to the folder where you want to save the file. Assign it a name and click **Save**.
   
.. image:: ../../../resources/en/training/t09/soc_output.png
   :align: center

9. Back at the **Load a Custom Soil Organic Carbon (SOC) dataset** click **OK** for the tool to run.

.. image:: ../../../resources/en/training/t09/custom_soc_menu2.png
   :align: center

10. A progress bar will appear showing the percentage of the task completed.      
   
.. image:: ../../../resources/en/training/t08/running.png
   :align: center

11. When the processing is completed, the imported soil organic carbon dataset will be loaded to QGIS.
   
.. image:: ../../../resources/en/training/t09/soc_output_map.png
   :align: center

Calculating soil organic carbon with custom data
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Once you have imported a custom soil organic carbon dataset, it is possible to 
calculate soil organic carbon degradation from that data. To do so, first 
ensure the custom soil organic carbon data is loaded within QGIS (see 
:ref:`load_custom_soc`).

1. To calculate soil organic carbon degradation from custom data, first click 
   on the (|iconCalculator|) icon on the Trends.Earth toolbar:

.. image:: ../../../resources/en/common/ldmt_toolbar_highlight_calculate.png
   :align: center

2. The "Calculate indicators" menu will open. Select "Soil organic carbon" 
   from the "Option 2: Use customized data" section.
   
.. image:: ../../../resources/en/training/t09/custom_soc_calculate.png
   :align: center

3. The "Calculate Soil Organic Carbon" window will open. Click the radio button 
   next to "Custom land cover dataset" and select either "Import" to import a 
   custom land cover dataset, or "Load existing" to load a land cover dataset 
   you have already processed in Trends.Earth. Be sure to select both an 
   "Initial layer" and a "Final layer". See the :ref:`tut_custom_lc` tutorial 
   for more information on loading land cover datasets. Once you have selected 
   both datasets, click next:

.. image:: ../../../resources/en/training/t09/calc_soc_select_lc.png
   :align: center

4. On the next screen, click the check box next to "Custom initial soil organic 
   carbon dataset", and then use the "Import" or "Load existing" buttons to 
   either import custom soil carbon layer (:ref:`load_custom_soc`) or to load 
   an existing one that has already been calculated:

.. image:: ../../../resources/en/training/t09/calc_soc_choose_soc_data.png
   :align: center

5. Click "Next". Now, choose the area you wish to run calculations for:

.. image:: ../../../resources/en/training/t09/calc_soc_choose_area.png
   :align: center

6. Click "Next". on the last screen, enter a task name or any notes you might 
   wish to save (this is optional) and then click "Calculate":

.. image:: ../../../resources/en/training/t09/calc_soc_final_page.png
   :align: center

7. A progress bar will appear on your screen. Do not quit QGIS or turn off your 
   computer until the calculation is complete.

.. image:: ../../../resources/en/training/t09/calc_soc_calculating.png
   :align: center

8. Once the calculation is complete, three layers will load onto your map: 1) 
   the final soil organic carbon layer, 2) the initial soil organic carbon 
   layer, and 3) the soil organic carbon degradation layer:

.. image:: ../../../resources/en/training/t09/calc_soc_done.png
   :align: center

9. For example, we can see areas of degradation in soil carbon around Kampala:

.. image:: ../../../resources/en/training/t09/calc_soc_deg_map.png
   :align: center

.. note::
    Refer to the :ref:`indicator-soc` tutorial for instructions on how to use 
    the imported soil organic carbon data to compute the final SDG 15.3.1 after 
    integration with land cover and land productivity.

Exploring NDVI (Plot Data)
--------------------------------
- **Coming soon**
