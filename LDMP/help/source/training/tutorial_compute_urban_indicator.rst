.. _indicator-11-3-1-tutorial:

SDG 11.3.1 - Land Consumption Rate
==================================
- **Objective**: Learn how to compute urban extent and population for 2000, 2005, 2010, 2015 in raster format and tabular outputs with areas estimated.

- **Estimated time of completion**: 40 minutes

- **Internet access**: Required

.. note:: `Download this page as a PDF for offline use 
   <../pdfs/Trends.Earth_Tutorial11_Urban_Change_SDG_Indicator.pdf>`_


.. note::
    For a detailed description on the concepts behind SDG 11.3.1, the data needs and a detailed description on how the data and analysis is handled in |trends.earth|, please refer to the background section: :ref:`indicator-11-3-1-background`.

https://github.com/ConservationInternational/trends.earth/releases/tag/0.64

Urban Mapper
--------------------------------------------   
The first step before analyzing urban change is to define the extent of built up areas. For that, we have created an interactive web interface called `Trends.Earth Urban Mapper <https://geflanddegradation.users.earthengine.app/view/trendsearth-urban-mapper>`_. This step is fundamental to make sure that the built up area identified by the indicators accurately reflects the conditions in your area of study. The Urban Mapper tool in GEE allows users to explore how changing different parameters impact the extent of the built up area data which will be then used to define changes in urban extent. 

1. Navigate to the `Trends.Earth Urban Mapper <https://geflanddegradation.users.earthengine.app/view/trendsearth-urban-mapper>`_.before you run the analysis in QGIS.


2. This tool can be used to analyze changes in built up area in almost any city of the world. Click on the **Search Places** window in the top center of the page and type the city you want to analyze. In this example we'll type "Kampala, Uganda" and click on the option showing right underneath.


3. This tool allows you to change three parameters in order to correctly identify the most appropriate built up extent for your city: Impervious surface index, night time lights index, and water frequency. The first time you run the tool in a new city, click **Run analysis** to see how the default parameters perform, and from there you can customize the analysis. To compare to satellite images, we can click on **Satellite** in the top right corner of the map window.

Now the map with the built up area defined by the default parameters will load into the map color coded in the following way:

	- Black: Built-up areas present since before 2000
	- Red: Built-up areas constructed between 2000 and 2005
	- Orange: Built-up areas constructed between 2005 and 2010
	- Yellow: Built-up areas constructed between 2010 and 2015

.. image:: /static/documentation/urban/calc_urban_mapper1.PNG
   :align: center
   
4. Now you should use your knowledge of the city to explore the data set. We can, for example, zoom in to an area in western Kampala to see how the default parameters perform (ISI: 30, NTL: 10, WFR: 25):

.. image:: /static/documentation/urban/calc_urban_mapper2.PNG
   :align: center
 
5. We can easily identify large square boundaries in the built up area data set which do not seem to match the spatial pattern displayed by the background satellite image. That is a sign that the Night time light indicator is set too high (i.e. it is removing from our built-up area map zones with low levels of light which should be included). This is a common situation in suburban areas with low levels of light. If we want to include those areas, we need to lower the value of the NTLI. In this case we'll try changing it from 10 to 5, and click **Run Analysis** again (ISI: 30, NTL: 5, WFR: 25).

.. image:: /static/documentation/urban/calc_urban_mapper3.PNG
   :align: center

6. You can see now the effect of changing that parameter. Those areas previously excluded (i.e. showing no data) now display information on the map.
   
7. If we consider that the overall extent of the built-up area shown in the map is correct, but that the density is too high, we can use the Impervious Surface Indicator to adjust it. If we increase the value of the ISI from 20 to 30, and click **Run analysis** a new layer will display showing overall lower levels of built-up. This happens because we are saying the tool "only consider built-up areas which have a value of impervious surface indicator of 30 or higher", so the higher we set this value to, the smaller the built-up area our map will display. The example we just run (ISI-30, NTLI-2, WF-25) would look something like this:

.. image:: /static/documentation/urban/calc_urban_mapper4.PNG
   :align: center
   
8. If we want to include more area, we do the opposite, and lower the ISI value. For example, with ISI-10, NTLI-2, WF-25, the same region in Kampala would look:

.. image:: /static/documentation/urban/calc_urban_mapper5.PNG
   :align: center
   
9. It is very important that you assess the impact of changing each of these parameters in your overall area of analysis (i.e. your city), since one set of parameters will be defined for the analysis. Scroll around, zoom in and out and change parameters until you feel you have found the set that better describes your city.

For example, the overall urban area in Kampala with ISI-10, NTLI-2, and WF-25 would look like this:

.. image:: /static/documentation/urban/calc_urban_mapper6.PNG
   :align: center
   
10. The third and last parameter which you can change in the Urban Mapper to define the built up area is Water Frequency. In most cases this parameter won't affect the results, but in some cases it does. For example, in Dubai where some areas originally covered with water have been filled and constructed, the water frequency parameter can be used to capture them. 

The water frequency parameter should be interpreted as follows: A pixel needs to be covered by water for at least X percent of the time for it to be considered water, otherwise it will be considered land". This means that the higher the value, the less water the map will show and the more land (i.e. built up if that is the case).

In the Dubai example, we can see these features in the satellite image.

.. image:: /static/documentation/urban/calc_urban_mapper8.PNG
   :align: center
   
But we can't see them in the built-up area map using the following parameters: ISI-35, NTLI-5, and WF-25.

.. image:: /static/documentation/urban/calc_urban_mapper7.PNG
   :align: center
   
11. If we change the Water frequency parameter to 80, we can start seeing the recently built-up areas in the water (ISI-35, NTLI-5, WF-80)

.. image:: /static/documentation/urban/calc_urban_mapper9.PNG
   :align: center

12. Once you have found the set of parameters which best work for your city, you are ready to run the analysis in QGIS.   
   
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

Before you begin filling out these settings, you will have to explore your area of interest using the interactive `Urban Mapper page <https://geflanddegradation.users.earthengine.app/view/trendsearth-urban-mapper>`_. This step is fundamental to make sure that the built up area identified by the indicators accurately reflects the conditions in your area of study.

Note that in that up to know we have tested parameters in Uganda and Dubai, and from now on we'll run things in Nairobi, so make sure that you have used the `Urban Mapper page <https://geflanddegradation.users.earthengine.app/view/trendsearth-urban-mapper>`_ and identified the best set of parameters for your city before running.

5. Settings

By default your window will be open on the Settings tab.

A. Select the Impervious Surface Index (ISI) by choosing a value between 0-100. The higher the value the smaller the urban area.

B. Select the Night Time Lights Index (NTLI) by choosing a value between 0-100. The higher the value the smaller the urban area.

C. Select the Water Frequency (WF) by choosing a value between 0-100. The higher the value the larger the urban area.

.. image:: /static/documentation/urban/calc_indicators_settings.PNG
   :align: center
   
6. Advanced

Click Next from the Settings tab to view the Advanced tab. Here you will need to define:

A. The thresholds for suburban and urban built up areas.

B. Define the area of largest captured open space (ha) which is the contiguous captured open space larger than this area that will be considered rural.

C. Select which population density dataset you would like to use for the analysis.

.. image:: /static/documentation/urban/calc_indicators_advanced.PNG
   :align: center

Click Next from the Advanced tab to view the Area tab. Here you will need to define the area for your analysis.

7. Area: You can select a country, region or city from the drop-down lists or upload an area from a file. If you select a city or upload a point location of a city, apply a buffer to the chosen area so that analysis encompasses all potential urban areas.

If you are using your own boundary shapefiile for analysis, we recommend you do not use buffers, since that will affect the area of analysis and the final area calculation.

.. image:: /static/documentation/urban/calc_indicators_area.PNG
   :align: center

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

8. Options: Name the task and some note on how you customized the parameters for your analysis for future reference.

When all the parameters have been defined, click "Calculate", and the task will be submitted to Google Earth Engine for computing. When the task is completed (processing time will vary depending on server usage, but for most countries it takes only a few minutes most of the time), you’ll receive an email notifying the successful completion.

.. image:: /static/documentation/urban/calc_indicators_options.PNG
   :align: center


9. Download results

.. image:: /static/common/ldmt_toolbar_highlight_tasks.png
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

4. Input: Load an existing .json file if it has not been populated within the dropdown automatically from your QGIS project.

.. image:: /static/documentation/urban/summary_input.PNG
   :align: center


5. Output: Select browse to navigate to a file on your computer and save the json file and excel table.

.. image:: /static/documentation/urban/summary_outputs.PNG
   :align: center

6. Area: Define the area for your analysis

.. image:: /static/documentation/urban/summary_area.PNG
   :align: center

7. Options: Enter a task name and notes for the analysis. This final step is calculated locally on your computer, it will load automatically in your QGIS project window. 

.. image:: /static/documentation/urban/summary_options.PNG
   :align: center
   
8. View results: A window will appear when the processing is complete. Select **OK**.

.. image:: /static/documentation/urban/success.PNG
   :align: center

After clicking OK, the four annual urban extent maps with their corresponding zoning will load into the QGIS project.
   
.. image:: /static/documentation/urban/urban_change.PNG
   :align: center
   
9. To explore the summary table, navigate to the folder in your computer where you saved the excel file and double click on it to open. If an error window appears, select the **Yes** and the summary will proceed to open.

.. image:: /static/documentation/urban/error.png
   :align: center   
   
.. image:: /static/documentation/urban/summary_table_sdg11.PNG
   :align: center 
   
10. In this table you'll find the area of the different city land cover classes (urban, suburban, fringe open space, capture open space and water) and the rural areas. You'll also find the population for each of the years analyzed (2000, 2005, 2010, and 2015) and the final SDG 11.3.1.
