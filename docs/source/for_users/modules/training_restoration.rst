.. _tut_carbon_sequestration_restoration:

Potential Carbon Sequestration under Restoration
==================================================

- **Objective**: Learn how to compute carbon sequestration under different forest restoration activities.

- **Estimated time of completion**: 20 minutes

- **Internet access**: Required

.. note::
    Refer to the :ref:`background_restoration` for background information on the datasets and 
	methodology used for this tutorial.

.. _compute_forest_data:

Estimate potential impacts of restoration
--------------------------------------------   
   
1. In the **Algorithms** tab in Trends.Earth plugin in QGIS, under the **Experimental** menu, select 
   **Potential change in biomass due to restoration - Above and below ground woody** menu.

.. image:: /static/common/te_experimental_restoration_menu.png
   :align: center   

2. Select the **Estimate potential impacts of restoration** menu by selecting **Execute locally**.

.. image:: /static/common/execute-remotely.png
   :align: center
   
3. A window will appear where you can select the paramaters for the restoration analysis.
   Select the type of restoration: terrestrial or coastal (mangrove). 
   Define the length of the intervention in year.
   
.. image:: /static/training/t13/biomass_change_restoration.png
   :align: center
  
4. Select **Change region** to define the area of interest.

.. image:: /static/common/change-region.png
   :align: center

.. note::
    The `Natural Earth Administrative Boundaries`_ provided in Trends.Earth 
    are in the `public domain`_. The boundaries and names used, and the 
    designations used, in Trends.Earth do not imply official endorsement or 
    acceptance by Conservation International Foundation, or by its partner 
    organizations and contributors.

    If using Trends.Earth for official purposes, it is recommended that users 
    choose an official boundary provided by the designated office of their 
    country.

.. _Natural Earth Administrative Boundaries: http://www.naturalearthdata.com

.. _Public Domain: https://creativecommons.org/publicdomain/zero/1.0

 - Use your own area file: If you want to use your own area of analysis, make sure the **Area from file** option is highlighted. Then click **Browse** and navigate to the folder in your computer where you have the file stored. 

5. Add a descriptive name and notes for the analysis
   
   Select **Schedule remote exectution**

.. image:: /static/training/t13/carbon_change.png
   :align: center

6. A light blue bar will temporarily show, indicating that the task was successfully submitted. The analysis will be run in Google servers and could take between 5 and 15 minutes depending on the size of the study area (larger areas tend to take longer).

Table summarizing likely changes in biomass
-----------------------------------------------

1. Go the the **Datasets** tab to **Add default layers from this dataset to map**.

.. image:: /static/training/t11/dataset_tab.png
   :align: center
   
2. In order to view the defined area of interest with reference data, select the **Load Base Map** in the **Datasets** tab.
   
.. image:: /static/training/t13/add_basemap.png
   :align: center
   
.. image:: /static/training/t13/biomass.png
   :align: center

3. Go back to the **Algorithms** tab in Trends.Earth plugin in QGIS, under the **Experimental** menu, select 
   **Potential change in biomass due to restoration - Above and below ground woody** menu and select the **Execute locally** button
   under **Table summarizing likely changes in biomass**.
   
.. image:: /static/training/t13/sequestration_from_restoration.png
   :align: center 

4. The layers will pre-populate in the data layer dropdowns. Confirm the region is the same area of interest, provide descriptive names and notes and select **Execute locally**.
    A spreadsheet comparing the final outputs is saved in your **trends_earth_data*** folder under your user account on your computer (e.g., C:\Users\mnoon\trends_earth_data).

.. image:: /static/training/t13/restoration_results_1.png
   :align: center

.. image:: /static/training/t13/restoration_results_2.png
   :align: center
   