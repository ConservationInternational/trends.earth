Calculate Indicators
========================
To select the methods and datasets to calculate the indicators that measured changes in primary productivity, select the globe icon (|iconCalculator|). 
This will open up the `Calculate Indicator` dialog box:
   
.. image:: /static/common/ldmt_toolbar_highlight_calculate.png
   :align: center

**Summary**
   
Sustainable Development Goal 15.3 intends to combat desertification, restore degraded land and soil, including land affected by desertification, drought and floods, and strive to achieve a land degradation-neutral world by 2030. In order to address this, we are measuring primary productivity, land cover and soil carbon to assess the annual change in degraded or desertified arable land (% of ha). The “Calculate indicators” button brings up a page that allows calculating datasets associated with the three SDG Target 15.3 sub indicators. For productivity and land cover, the toolbox implements the Tier 1 recommendations of the Good Practice Guidance lead by CSIRO. For productivity, users can calculate trajectory, performance, and state. For Land Cover, users can calculate land cover change relative to a baseline period, and enter a transition matrix indicating which transitions indicate degradation, stability, or improvement.

Select which Indicator you would like to calculate

•	Productivity: measures the trajectory, performance and state of primary productivity

•	Land cover: calculates land cover change relative to a baseline period, enter a transition matrix indicating which transitions indicate degradation, stability or improvement.

•	Soil carbon: under review following the Good Practice Guidance (CSIRO, 9-2017).
   
.. image:: /static/documentation/calculate/image021.png
   :align: center
   
Productivity
------------
**Summary**

Productivity measures the trajectory, performance and state of primary productivity using either 8km GIMMS3g.v1 AVHRR or 250m MODIS datasets. The user can select one or multiple indicators to calculate, the NDVI dataset, name the tasks and enter in explanatory notes for their intended reporting area.

NOTE: The valid date range is set by the NDVI dataset selected within the first tab: AVHRR dates compare 1982-2015 and MODIS 2001-2016.

Productivity Trajectory
~~~~~~~~~~~~~~~~~~~~~~~
1) Trajectory is related to the rate of change of productivity over time. 

a) Users can select NDVI trends, Rain Use Efficiency (RUE), Pixel RESTREND or Water Use Efficiency (WUE) to determine the trends in productivity over the time period selected. 

b) The starting year and end year will determine de period on which to perform the analysis.

c) The initial trend is indicated by the slope of a linear regression fitted across annual productivity measurements over the entire period as assessed using the Mann-Kendall Z score where degradation occurs where z= ≤ -1.96 (CSIRO, 2017).

d) Degradation in each reporting period should be assessed by appending the recent annual NPP values (measured in the toolbox as annual integral of NDVI) to the baseline data and calculating the trend and significance over the entire data series and the most recent 8 years of data (CSIRO, 2017).

e) Climate datasets need to be selected to perform climate corrections using RESTREND, Rain Use Efficiency or Water Use Efficiency (refer to table 1 for full list of climate variables available in the toolbox).

**Calculating Trajectory**

1) Check next to Trajectory

2) Select NDVI dataset to use

.. image:: /static/documentation/calculate/image022.png
   :align: center

3) Assign a name to the task. Use descriptive names including study area, periods analyzed and datasets used, to be able to refer to them later.

.. image:: /static/documentation/calculate/image023.png
   :align: center
   
4) In the tab “Trajectory”, select the method to be used to compute the productivity trajectory analysis. The options are:

* NDVI trend: This dataset shows the trend in annually integrated NDVI time series (2003-2015) using MODIS (250m) dataset (MOD13Q1) or AVHRR (8km; GIMMS3g.v1). The normalized difference vegetation index (NDVI) is the ratio of the difference between near-infrared band (NIR) and the red band (RED) and the sum of these two bands (Rouse et al., 1974; Deering 1978) and reviewed in Tucker (1979). 

* Rain use efficiency (RUE): is defined as the ratio between net primary production (NPP), or aboveground NPP (ANPP), and rainfall. It has been increasingly used to analyze the variability of vegetation production in arid and semi-arid biomes, where rainfall is a major limiting factor for plant growth

* Pixel RESTREND: The pointwise residual trend approach (P-RESTREND), attempts to adjust the NDVI signals from the effect of particular climatic drivers, such as rainfall or soil moisture, using a pixel-by-pixel linear regression on the NDVI time series and the climate signal, in this case precipitation from GCPC data at 250m resolution. The linear model and the climatic data is used then to predict NDVI, and to compute the residualsbetween the observed and climate-predicted NDVI annual integrals. The NDVI residual trend is finally plotted to spatially represent overall trends in primary productivity independent of climate. 

* Water use efficiency (WUE):  refers to the ratio of water used in plant metabolism to water lost by the plant through transpiration. 

.. image:: /static/documentation/calculate/image024.png
   :align: center

Productivity Performance
~~~~~~~~~~~~~~~~~~~~~~~~
Performance is a comparison of how productivity in an area compares to productivity in similar areas at the same point in time.

* Select the period of analysis. This determines the initial degradation state and serves as a comparison to assess change in degradation for each reporting period.

* The initial productivity performance is assessed in relation to the 90th percentile of annual productivity values calculated over the baseline period amongst pixels in the same land unit. The toolbox defines land units as regions with the same combination of Global Agroecological Zones and land cover (300m from ESA CCI). Pixels with an NPP performance in the lowest 50% of the distribution for that particular unit may indicate degradation in this metric (CSIRO, 2017).

**Calculating Performance**

1) Select the baseline period of comparison. This determines the initial degradation state and serves as a comparison to assess change in degradation for each reporting period.

.. image:: /static/documentation/calculate/image025.png
   :align: center

2) The initial productivity performance is assessed in relation to the 90th percentile of annual productivity values calculated over the baseline period amongst pixels in the same land unit. Pixels with an NPP performance in the lowest 50% of the historical range may indicate degradation in this metric (CSIRO, 2017).

3) Contemporary Productivity Performance for each reporting period should be calculated from an average of the years between the previous (or baseline) assessment up to the current year (CSIRO, 2017).

Productivity State
~~~~~~~~~~~~~~~~~~~~
State is a comparison of how current productivity in an area compares to past productivity in that area.

* The user selects the baseline period and comparison period to determine the state for both existing and emerging degradation.

* The baseline period classifies annual productivity measurements to determine initial degradation. Pixels in the lowest 50% of classes may indicate degradation (CSIRO, 2017).

* Productivity State assessments for each reporting period should compare the average of the annual productivity measurements over the reporting period (up to 4 years of new data) to the productivity classes calculated from the baseline period. NPP State classifications that have changed by two or more classes between the baseline and reporting period indicate significant productivity State change (CSIRO, 2017).

**Calculating State**

1) The user selects the baseline period and comparison period to determine the state for both existing and emerging degradation.

.. image:: /static/documentation/calculate/image026.png
   :align: center

2) The baseline period classifies annual productivity measurements to determine initial degradation. Pixels in the lowest 50% of classes may indicate degradation (CSIRO, 2017).

3) State assessments for each reporting period should compare the average of the annual productivity measurements over the reporting period (up to 4 years of new data) to the productivity classes calculated from the baseline period. NPP State classifications that have changed by two or more classes between the baseline and reporting period indicate significant productivity State change (CSIRO, 2017).

**Productivity - Area of interest**

The final step before submitting the task to Google Earth Engine, is to define the study area on which to perform the analysis. The toolbox allows this task to be completed in one of two ways:

1. The user selects first (i.e. country) and second (i.e. province or state) administrative boundary from a drop down menu. 

2. The user can upload a shapefile with an area of interest. 

NOTE: This boundary should have only one polygon, i.e. when uploading a country with outlying islands, there will be multiple geometries drawn separately. By merging the polygons, the analysis will be run on the entire study area as opposed to a single polygon.

.. image:: /static/documentation/calculate/image027.png
   :align: center
 
.. image:: /static/documentation/calculate/image028.png
   :align: center

**Submit task**

When all the parameters have been defined, click Calculate, and the task will be submitted to Google Earth Engine for computing. When the task is completed (processing time will vary depending on server usage, but for most countries it takes only a few minutes most of the time), you’ll receive an email notifying the successful completion.

Land Cover
----------
**Summary**

Changes in land cover is one of the indicators used to track potential land degradation which need to be reported to the UNCCD and to track progress towards SDG 15.3.1. While some land cover transitions indicate, in most cases, processes of land degradation, the interpretation of those transitions are for the most part context specific. For that reason, this indicator requires the input of the user to identify which changes in land cover will be considered as degradation, improvement or no change in terms of degradation. The toolbox allows users to calculate land cover change relative to a baseline period, enter a transition matrix indicating which transitions indicate degradation, stability or improvement.

**Calculating Land cover changes**

1) Click on the Calculate Indicators button from the toolbox bar, then select Land cover.
   
.. image:: /static/documentation/calculate/image029.png
   :align: center

2) Set up tab: Allows the user to select the starting year and ending year

a) The baseline should be considered over an extended period over a single date (e.g. 1/1/2000-12/31/2015).

b) User selects target year. 

c) Metadata: User enters unique task name and notes for the analyses.
   
.. image:: /static/documentation/calculate/image030.png
   :align: center
   
3) Transition matrix tab

a) User selects the transition matrix value of land cover transitions for each transition between the 6 IPCC land cover classes. For example: 

i) The default for cropland to cropland is 0 because the land cover stays the same and is therefore stable.

ii) The default for forest to cropland is -1 because forest is likely cut to clear way for agriculture and would be considered deforestation.

iii) The transition can be defined as stable in terms of land degradation, or indicative of degradation (-1) or improvement (1).

b) Users can keep the default values or create unique transition values of their own.
   
.. image:: /static/documentation/calculate/image031.png
   :align: center
   
By default, and following the CSIRO best practices guidance document, the major land cover change processes that are classified as degradation are:

1) Deforestation (forest to cropland or settlements)

2) Urban expansion (grassland, cropland wetlands or otherland to settlements)

3) Vegetation loss (forest to grassland, otherland or grassland, cropland to other land)

4) Inundation (forest, grassland, cropland to wetlands)

5) Wetland drainage (wetlands to cropland or grassland)

6) Withdrawal of agriculture (croplands to grassland)

7) Woody encroachment (wetlands to forest)


The major land cover change processes that are not considered degradation are:

1) Stable (land cover class remains the same over time period)

2) Afforestation (grassland, cropland to forest; settlements to forest)

3) Agricultural expansion (grassland to cropland; settlements or otherland to cropland)

4) Vegetation establishment (settlements or otherland to settlements)

5) Wetland establishment (settlements or otherland to wetlands)

6) Withdrawal of settlements (settlements to otherland)

It is important to remember that those are suggested interpretations, and should be evaluated and adjusted considering the local conditions of the regions in for which the analysis will be performed.

**Land cover - Area of interest**

The final step before submitting the task to Google Earth Engine, is to define the study area on which to perform the analysis. The toolbox allows this task to be completed in one of two ways:

1. The user selects first (i.e. country) and second (i.e. province or state) administrative boundary from a drop-down menu. 

2. The user can upload a shapefile with an area of interest.
   
.. image:: /static/documentation/calculate/image032.png
   :align: center
   
Soil Carbon
-----------
**Coming soon!**

.. toctree::
   :maxdepth: 2