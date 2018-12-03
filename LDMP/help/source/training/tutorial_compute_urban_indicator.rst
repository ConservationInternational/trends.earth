SDG 11.3.1 - Land Consumption Rate
==================================
- **Objective**: Learn how to compute urban extent for 2000, 2005, 2010, 2015 in raster format and tabular outputs with areas estimated.

- **Estimated time of completion**: 20 minutes

- **Internet access**: Required

.. note:: `Download this page as a PDF for offline use 
   <../pdfs/Trends.Earth_Tutorial11_Urban_Change_SDG_Indicator.pdf>`_

.. _compute_urban:

Compute urban area change
--------------------------------------------   
1.	Select the Calculate icon (|iconCalculator|) from the Trends.Earth plugin in QGIS.

.. image:: /static/common/ldmt_toolbar_highlight_calculate.png
   :align: center   

2. The **Calculate Indicators** menu will open. In that window, click on **Urban change and land consumption indicators (SDG indicator 11.3.1)** button.

.. image:: /static/documentation/urban/calc_indicators.PNG
   :align: center

3. Select Step 1: Calculate urban change spatial layers

.. image:: /static/documentation/urban/calc_urban.PNG
   :align: center

4. The **Calculate Urban Area Change Metrics** menu will open. In that window, you will step through the four tabs to set the parameters for your analysis.

Before you begin filling out these settings, you may wish to explore your area of interest using the interactive `Urban Mapper page <https://geflanddegradation.users.earthengine.app/view/trendsearth-urban-mapper>`_

.. note::
    Refer to the :ref:`urban_mapper` section of this manual for a detailed 
    explanation of how each of these sub-indicators is computed in 
    |trends.earth|

5. Settings

.. image:: /static/documentation/urban/calc_indicators_settings.PNG
   :align: center
   
By default your window will be open on the Settings tab. 
A. Select the Impervious Surface Index (ISI) by choosing a value between 0-100. The higher the value the smaller the urban area.
B. Select the Night Time Lights Index (NTLI) by choosing a value between 0-100. The higher the value the smaller the urban area.
C. Select the Water Frequency (WF) by choosing a value between 0-100. The higher the value the larger the urban area.

6. Advanced

.. image:: /static/documentation/urban/calc_indicators_advanced.PNG
   :align: center

Click Next from the Settings tab to view the Advanced tab. Here you will need to define the thresholds for suburban and urban built up areas.
A. Define the area of largest captured open space (ha) which is the contiguous captured open space larger than this area that will be considered rural.
B. Select which population density dataset you would like to use for the analysis.

7. Area

.. image:: /static/documentation/urban/calc_indicators_area.PNG
   :align: center

Click Next from the Advanced tab to view the Area tab. Here you will need to define the area for your analysis.

.. note::
    The provided boundaries are from `Natural Earth 
    <http://www.naturalearthdata.com>`_, and are in the `public domain
    <https://creativecommons.org/publicdomain>`_. The boundaries and names 
    used, and the designations used, in Trends.Earth do not imply official 
    endorsement or acceptance by Conservation International Foundation, or by 
    its partner organizations and contributors.

    If using Trends.Earth for official purposes, it is recommended that users 
    choose an official boundary provided by the designated office of their 
    country.

You can select a country, region or city from the dropdown lists or upload an area from a file. If you select a city or upload a point location of a city, apply a buffer to the chosen area so that analysis encompasses all potential urban areas.

8. Options

.. image:: /static/documentation/urban/calc_indicators_options.PNG
   :align: center

Name the task and some note on how you customized the parameters for your analysis for future reference.
When all the parameters have been defined, click "Calculate", and the task will be submitted to Google Earth Engine for computing. When the task is 
completed (processing time will vary depending on server usage, but for most countries it takes only a few minutes most of the time), you’ll receive an 
email notifying the successful completion.

9. Download results

.. image:: /static/common/ldmt_toolbar_highlight_download.png
   :align: center
   
When the Google Earth Engine task has completed and you received the email, click "Refresh List" and the status will show FINISHED.  

.. image:: /static/documentation/urban/download_task.PNG
   :align: center
   
Click on the task and select "Download results" at the bottom of the window. A pop up window will open for you to select where to save the layer and to assign it a name. 

.. image:: /static/documentation/urban/save_json.PNG
   :align: center
   
Then click "Save". The layer will be saved on your computer and automatically loaded into your current QGIS project.

.. image:: /static/documentation/urban/urban_area_change.PNG
   :align: center

Compute urban area for 2000, 2005, 2010 and 2015
--------------------------------------------------
1.	Select the Calculate icon (|iconCalculator|) from the Trends.Earth plugin in QGIS.

.. image:: /static/common/ldmt_toolbar_highlight_calculate.png
   :align: center   

2. The **Calculate Indicators** menu will open. In that window, click on **Urban change and land consumption indicators (SDG indicator 11.3.1)** button.

.. image:: /static/documentation/urban/calc_indicators.PNG
   :align: center

3. Select Step 2: Calculate urban change summary table for city.

.. image:: /static/documentation/urban/calc_urban2.PNG
   :align: center

4. Input

.. image:: /static/documentation/urban/summary_input.PNG
   :align: center

Load an existing .json file if it has not been populated within the dropdown automatically from your QGIS project.

5. Output

.. image:: /static/documentation/urban/summary_outputs.PNG
   :align: center

Select browse to navigate to a file on your computer and save the json file and excel table.

6. Area

.. image:: /static/documentation/urban/summary_area.PNG
   :align: center
   
Define the area for your analysis

7. Options 

.. image:: /static/documentation/urban/summary_options.PNG
   :align: center
   
Enter a task name and notes for the analysis. This final step is calculated locally on your computer, it will load automatically in your QGIS project window. 

8. View results
A window will appear when the summary is complete. Select **OK**.

.. image:: /static/training/t11/success.png
   :align: center   

9. If an error window appears, select the **Yes** and the summary will proceed to open.

.. image:: /static/training/t11/error.png
   :align: center   
   
10. The summary table will appear and a spatial layer will be added to your QGIS project.

.. image:: /static/documentation/urban/summary_table.PNG
   :align: center 
   
.. image:: /static/documentation/urban/urban_change.PNG
   :align: center

.. _urban_mapper:
   
Urban Mapper
--------------------------------------------   
The Urban Mapper tool in GEE allows users to explore how changing different parameters impact the final output. Here we look at Kampala, Uganda:

.. image:: /static/documentation/urban/calc_urban_mapper1.PNG
   :align: center
   
To get a better look at the fine details of the layers, we can zoom in to an area with the default parameters (ISI-20, NTLI-10, WF-25):

.. image:: /static/documentation/urban/calc_urban_mapper2.PNG
   :align: center
   
Explore the changes to the map layers with changes to the Night-time lights parameter (ISI-20, NTLI-2, WF - 25)

.. image:: /static/documentation/urban/calc_urban_mapper3.PNG
   :align: center
   
See how this changes with a higher Impervious Surface value (ISI-30, NTLI-2, WF-25)

.. image:: /static/documentation/urban/calc_urban_mapper4.PNG
   :align: center
   
The area considered urban has decreased in size. Change the Impervious Surface to a lower number to see how it impacts the urban area (ISI-10, NTLI-2, WF-25)

.. image:: /static/documentation/urban/calc_urban_mapper5.PNG
   :align: center
   
Zoom out to view the impact of these changes on the overall urban area in Kampala (ISI-10, NTLI-2, WF-25)

.. image:: /static/documentation/urban/calc_urban_mapper6.PNG
   :align: center
   
In contrast, we can look at Dubai, an arid city.

.. image:: /static/documentation/urban/calc_urban_mapper8.PNG
   :align: center
   
Adjusting the parameters we can see that Dubai would require a different set of parameters than Kampala (ISI-35, NTLI-5, WF-25)

.. image:: /static/documentation/urban/calc_urban_mapper7.PNG
   :align: center
   
Change the Water frequency parameter to see the impact on the man-made islands of Dubai(ISI-35, NTLI-5, WF-80)

.. image:: /static/documentation/urban/calc_urban_mapper9.PNG
   :align: center