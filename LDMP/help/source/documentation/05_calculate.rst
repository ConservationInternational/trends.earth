Calculate indicators
========================
.. image:: /static/common/ldmt_toolbar_highlight_calculate.png
   :align: center

**Summary**
   
Sustainable Development Goal 15.3 intends to combat desertification, restore degraded land and soil, including land affected by desertification, drought and floods, and strive to achieve a land degradation-neutral world by 2030. In order to assess the progress to this goal, we need to measure changes in primary productivity, land cover, and soil organic carbon to assess the annual change in degraded or desertified arable land (% area or km²). 

**Calculations**

To select the methods and datasets to calculate the indicators click on the calculator icon (|iconCalculator|). This will open up the `Calculate Indicator` dialog box.

There are several options for calculating the SDG 15.3.1 Indicator:

Step 1: Prepare sub-indicators

Option 1: Use default UNCCD data

or

Option 2: Customize data
Select which Indicator you would like to calculate

•	Productivity: measures the trajectory, performance and state of primary productivity

•	Land cover: calculates land cover change relative to a baseline period, enter a transition matrix indicating which transitions indicate degradation, stability or improvement.

•	Soil carbon: compute changes in soil organic carbon as a consequence of changes in land cover.

Step 2: Calculate final SDG 15.3.1 indicator and summary table

.. image:: /static/documentation/05_calculate/image021.png
   :align: center

Step 1: Prepare sub-indicators
------------------------------

Option 1: Use default UNCCD data
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
**Summary**
This allows users to calculate all three sub-indicators in one step. Select the `Calculate all three sub-indicators in one step` button

1. Select the parameters for Setup. The Period is the Initial and Final year for the analysis and select one of the two Land Productivity datasets. Select Next.

.. image:: /static/documentation/05_calculate/image022.png
   :align: center
   
2. Select the Land Cover dataset. The first option is the default ESA dataset.

.. image:: /static/documentation/05_calculate/image023.png
   :align: center

3. Select Edit definition to change the aggregation from the ESA Land Cover dataset into 7 classes.

.. image:: /static/documentation/05_calculate/image024.png
   :align: center

The second option allows users to upload a custom land cover dataset. This requires two datasets to compare change over time. Select Next.

.. image:: /static/documentation/05_calculate/image025.png
   :align: center

4. The user can now define the effects of land cover change and how it is classified as degrading or improving.

.. image:: /static/documentation/05_calculate/image026.png
   :align: center

5. Select an area to run the analysis or upload a shapefile boundary

.. image:: /static/documentation/05_calculate/image027.png
   :align: center

6. Name the task and make notes for future reference

7. Click on `Calculate` to submit your task to Google Earth Engine

   
Option 2: Customize data
~~~~~~~~~~~~~~~~~~~~~~~~

.. image:: /static/documentation/05_calculate/image028.png
   :align: center

**Summary**
Select which Indicator you would like to calculate.
 
Productivity
------------
**Summary**

Productivity measures the trajectory, performance and state of primary productivity using either 8km AVHRR or 250m MODIS datasets. The user can select one or multiple indicators to calculate, the NDVI dataset, name the tasks and enter in explanatory notes for their intended reporting area.

NOTE: Refer to the **SDG Indicator 15.3.1** section of this manual for detailed explanations of how each of this subindicators is computed in |trends.earth|

NOTE: The valid date range is set by the NDVI dataset selected within the first tab: AVHRR dates compare 1982-2015 and MODIS 2001-2016.

Productivity Trajectory
~~~~~~~~~~~~~~~~~~~~~~~

Trajectory assesses the rate of change of productivity over time. 

**Calculating Trajectory**

1) Select an indicator to calculate

2) Select NDVI dataset to use and select Next

.. image:: /static/documentation/05_calculate/image029.png
   :align: center

3) In the tab `Advanced`, select the method to be used to compute the productivity trajectory analysis. The options are:

* **NDVI trend**: This dataset shows the trend in annually integrated NDVI time series (2001-2015) using MODIS (250m) dataset (MOD13Q1) or AVHRR (8km; GIMMS3g.v1). The normalized difference vegetation index (NDVI) is the ratio of the difference between near-infrared band (NIR) and the red band (RED) and the sum of these two bands (Rouse et al., 1974; Deering 1978) and reviewed in Tucker (1979). 


* **RUE**: is defined as the ratio between net primary production (NPP), in this case annual integrals of NDVI, and rainfall. It has been increasingly used to analyze the variability of vegetation production in arid and semi-arid biomes, where rainfall is a major limiting factor for plant growth


* **RESTREND**: this method attempts to adjust the NDVI signals from the effect of particular climatic drivers, such as rainfall or soil moisture, using a pixel-by-pixel linear regression on the NDVI time series and the climate signal. The linear model and the climatic data is used then to predict NDVI, and to compute the residuals between the observed and climate-predicted NDVI annual integrals. The NDVI residual trend is finally plotted to spatially represent overall trends in primary productivity independent of climate. 

* **WUE**: is defined as the ratio between net primary production (NPP), in this case annual integrals of NDVI, and evapotranspiration.

.. image:: /static/documentation/05_calculate/image030.png
   :align: center

Productivity Performance
~~~~~~~~~~~~~~~~~~~~~~~~
Performance is a comparison of how productivity in an area compares to productivity in similar areas at the same point in time.

**Calculating Performance**

1) The user only needs to select the start and end years of the period of analysis  for comparison. 

NOTE: Refer to the **SDG Indicator 15.3.1** section of this manual for detailed explanations of how this subindicator is computed in |trends.earth|

Productivity State
~~~~~~~~~~~~~~~~~~
State performs a comparison of how current productivity in an area compares to past productivity.

**Calculating State**

1) The user only needs to define baseline and comparison periods for the computation of the State subindicator.

NOTE: Refer to the **SDG Indicator 15.3.1** section of this manual for detailed explanations of how this subindicator is computed in |trends.earth|

**Productivity - Area of interest**

The next step is to define the study area on which to perform the analysis. The toolbox allows this task to be completed in one of two ways:

1. The user selects first (i.e. country) and second (i.e. province or state) administrative boundary from a drop-down menu. 

2. The user can upload a shapefile with an area of interest. Select Next.

.. image:: /static/documentation/05_calculate/image031.png
   :align: center
   
3. The next step is to write a Task name and some notes to indicate which options were selected for the analysis.

.. image:: /static/documentation/05_calculate/image032.png
   :align: center
   
4. When all the parameters have been defined, click `Calculate`, and the task will be submitted to Google Earth Engine for computing. When the task is completed (processing time will vary depending on server usage, but for most countries it takes only a few minutes most of the time), you’ll receive an email notifying the successful completion.

5. When the Google Earth Engine task has completed and you received the email, click `Refresh List` and the status will show FINISHED. Click on the task and select `Download results` at the bottom of the window. A pop up window will open for you to select where to save the layer and to assign it a name. Then click `Save`. The layer will be saved on your computer and automatically loaded into yoour current QGIS project.

.. image:: /static/documentation/05_calculate/output_productivity.png
   :align: center

Land Cover
----------
**Summary**

Changes in land cover is one of the indicators used to track potential land degradation which need to be reported to the UNCCD and to track progress towards SDG 15.3.1. While some land cover transitions indicate, in most cases, processes of land degradation, the interpretation of those transitions are for the most part context specific. For that reason, this indicator requires the input of the user to identify which changes in land cover will be considered as degradation, improvement or no change in terms of degradation. The toolbox allows users to calculate land cover change relative to a baseline period, enter a transition matrix indicating which transitions indicate degradation, stability or improvement.

**Calculating Land cover changes**

1. Click on the Calculate Indicators button from the toolbox bar, then select Land cover.
   
.. image:: /static/documentation/05_calculate/image033.png
   :align: center

2. Within the `Land Cover Setup tab` the user selects the baseline and target years

.. image:: /static/documentation/05_calculate/image034.png
   :align: center
   
3. The land cover aggregation can be customized using the 'Edit definition' button. The user can define their own aggregation of land cover classes from the 37 ESA land cover classes to the 7 UNCCD categories.

a)	Select the dial button for the `Custom` option and select `Create new definition` 

b)	Edit the aggregation suitable for the area of interest

c)	Select `Save definition` and select Next

.. image:: /static/documentation/05_calculate/image035.png
   :align: center
   
4. Within the `Define Degradation tab` user define the meaning of each land cover transition in terms of degradation. The options are: stable (0), degradation (-) or improvement (+). For example, the default for cropland to cropland is 0 because the land cover stays the same and is therefore stable. The default for forest to cropland is -1 because forest is likely cut to clear way for agriculture and would be considered deforestation. The user is encouraged to thoroughly evaluate the meaning of each transition based on their knowledge of the study area, since this matrix will have an important effect on the land degradation identified by this subindicator.

Users can keep the default values or create unique transition values of their own.
   
.. image:: /static/documentation/05_calculate/image036.png
   :align: center
   
5. The next step is to define the study area on which to perform the analysis. The toolbox allows this task to be completed in one of two ways:

a. The user selects first (i.e. country) and second (i.e. province or state) administrative boundary from a drop-down menu. 

b. The user can upload a shapefile with an area of interest.
   
.. image:: /static/documentation/05_calculate/image037.png
   :align: center

6. The next step is to add the task name and relevant notes for the analysis.

.. image:: /static/documentation/05_calculate/image038.png
   :align: center
   
7. When all the parameters have been defined, click `Calculate`, and the task will be submitted to Google Earth Engine for computing. When the task is completed (processing time will vary depending on server usage, but for most countries it takes only a few minutes most of the time), you’ll receive an email notifying the successful completion.


8. When the Google Earth Engine task has completed and you received the email, click `Refresh List` and the status will show FINISHED. Click on the task and select `Download results` at the bottom of the window. A pop up window will open for you to select where to save the layer and to assign it a name. Then click `Save`. The layer will be saved on your computer and automatically loaded into yoour current QGIS project.

.. image:: /static/documentation/05_calculate/output_landcover.png
   :align: center
   
Soil Carbon
-----------
**Summary**

Soil Organic Carbon is calculated as a proxy for carbon stocks. It is measured using soil data and changes in land cover.

**Calculating changes in soil organic carbon**

.. image:: /static/documentation/05_calculate/image039.png
   :align: center

1. Select Soil organic carbon button under Calculate Indicators

.. image:: /static/documentation/05_calculate/image040.png
   :align: center

2. The Land Cover Setup tab allows the user to define the period for analysis with the baseline and target year. Users can select the Edit definition button to change the land cover aggregation method or upload a datasets.   

.. image:: /static/documentation/05_calculate/image041.png
   :align: center
   
3. The `Advanced` tab allows users to specify the Climate regime.

.. image:: /static/documentation/05_calculate/image042.png
   :align: center
   
4. Users can select an area or upload a polygon shapefile for analysis
   
.. image:: /static/documentation/05_calculate/image043.png
   :align: center

6. The next step is to add the task name and relevant notes for the analysis.
   
7. When all the parameters have been defined, click `Calculate`, and the task will be submitted to Google Earth Engine for computing. When the task is completed (processing time will vary depending on server usage, but for most countries it takes only a few minutes most of the time), you’ll receive an email notifying the successful completion.

8. When the Google Earth Engine task has completed and you received the email, click `Refresh List` and the status will show FINISHED. Click on the task and select `Download results` at the bottom of the window. A pop up window will open for you to select where to save the layer and to assign it a name. Then click `Save`. The layer will be saved on your computer and automatically loaded into yoour current QGIS project.

.. image:: /static/documentation/05_calculate/output_soc.png
   :align: center

Compute SDG Indicator 15.3.1
----------------------------

1. Once you have computed the three sub-indicators (productivity, land cover and soil organic carbon), and they are loaded into the QGIS project. Click on the Calculate icon (|iconCalculator|). This will open up the `Calculate Indicator` dialog box. This time click on Step 2 `Calculate final SDG 15.3.1 indicator and summary table`.

2. The input window will open already populated with the correct subindicators (that if you have them loaded to the QGIS map)

.. image:: /static/documentation/05_calculate/sdg_input.png
   :align: center

3. Select the name and location where to save the output ratser layer and the excel file with the areas computed.  
 
.. image:: /static/documentation/05_calculate/sdg_output.png
   :align: center

4. Define the area of analysis. In this example, the country boundary.
  
.. image:: /static/documentation/05_calculate/sdg_area.png
   :align: center
   
5. Give a name to the task and click `Calculate`
   
.. image:: /static/documentation/05_calculate/sdg_options.png
   :align: center

6. This calculation is run on your computer, so depending on the size of the area and the computing power of your computer, it could take a few minutes. When completed, the final SDG indicator will be loaded into the QGIS map and the Excel file with the areas will be saved in the folder you selected. when done, a message will pop up.

.. image:: /static/documentation/05_calculate/sdg_done.png
   :align: center
   
7. Click OK and two layers will be loaded to your map: the **5 classes productivity** and the **SDG 15.3.1** indicators.

.. image:: /static/documentation/05_calculate/sdg_maps.png
   :align: center

8. If you navigate to the folder you selected for storing the files, you can open the Excel files with the areas computed for each of the subindicators and the final SDG. NOTE: You may get an error message when opening the file, just click ok and the file will open regardless. We are working to fix this error.

.. image:: /static/documentation/05_calculate/sdg_excel.png
   :align: center
  
   
.. toctree::
   :maxdepth: 2
