��    T      �              \  "   ]     �     �     �     �  !   �  #         $     4  D   @  T   �  �   �  �   h     �  �       �
  V   �
  �   N  P    1   o  �  �  {   R  4   �  �     
   �  �   �  B   �  �  �  �   P    �     �  u  ^     �     �     �  �       �  -  �  T   �  ,  F     s  �   �  �   <  2   �  G        Z  �   f  ;   ?  �  {  h   !  �  u!  8  !%  h   Z&  h   �&  �   ,'  �   �'  �  w(  b  >*  y  �,  N   .  Y   j.  {   �.  9   @/  x   z/  x   �/  }   l0  �   �0  F   �1     2  J   2     g2  �   �2  R   3  �   _3  B   4  U   O4  �   �4  4   *5  <   _5  V  �5  2   �6  4   &7  '   [7  �  �7  "   q9     �9     �9     �9     �9  !   �9  #   :     8:     H:  D   T:  T   �:  �   �:  �   |;     <  �  %<     �>  V   ?  �   b?  P  2@  1   �A  �  �A  {   fC  4   �C  �   D     �D  �   �D  B   �E  �  �E  �   iG    �G  �   �H  u  yI  
   �K     �K     L  �  &L     �M  -  �M  T   
O  ,  _O     �P  �   �P  �   UQ  2   �Q  G   +R     sR  �   �R  ;   ^S  �  �S  q   +U  �  �U  8  IY  h   �Z  h   �Z  �   T[  �   �[  �  �\  b  f^  y  �`  N   Cb  Y   �b  {   �b  9   hc  x   �c  x   d  }   �d  �   e  F   �e     .f  J   Df     �f  �   �f  R   4g  �   �g  B   4h  U   wh  �   �h  4   Ri  <   �i  V  �i  2   k  4   Nk  '   �k   **Calculating Land cover changes** **Calculating Performance** **Calculating State** **Calculating Trajectory** **Coming soon!** **Land cover - Area of interest** **Productivity - Area of interest** **Submit task** **Summary** Afforestation (grassland, cropland to forest; settlements to forest) Agricultural expansion (grassland to cropland; settlements or otherland to cropland) Assign a name to the task. Use descriptive names including study area, periods analyzed and datasets used, to be able to refer to them later. By default, and following the UNCCD best practices guidance document, the major land cover change processes that are classified as degradation are: Calculate Indicators Changes in land cover is one of the indicators used to track potential land degradation which need to be reported to the UNCCD and to track progress towards SDG 15.3.1. While some land cover transitions indicate, in most cases, processes of land degradation, the interpretation of those transitions are for the most part context specific. For that reason, this indicator requires the input of the user to identify which changes in land cover will be considered as degradation, improvement or no change in terms of degradation. The toolbox allows users to calculate land cover change relative to a baseline period, enter a transition matrix indicating which transitions indicate degradation, stability or improvement. Check next to Trajectory Click on the Calculate Indicators button from the toolbox bar, then select Land cover. Climate datasets need to be selected to perform climate corrections using RESTREND, Rain Use Efficiency or Water Use Efficiency (refer to table 1 for full list of climate variables available in the toolbox). Contemporary Productivity Performance for each reporting period should be calculated from an average of the years between the previous (or baseline) assessment up to the current year `(UNCCD 2017) <http://www2.unccd.int/sites/default/files/relevant-links/2017-10/Good%20Practice%20Guidance_SDG%20Indicator%2015.3.1_Version%201.0.pdf>`_. Deforestation (forest to cropland or settlements) Degradation in each reporting period should be assessed by appending the recent annual NPP values (measured in the toolbox as annual integral of NDVI) to the baseline data and calculating the trend and significance over the entire data series and the most recent 8 years of data `(UNCCD 2017) <http://www2.unccd.int/sites/default/files/relevant-links/2017-10/Good%20Practice%20Guidance_SDG%20Indicator%2015.3.1_Version%201.0.pdf>`_. In the tab “Trajectory”, select the method to be used to compute the productivity trajectory analysis. The options are: Inundation (forest, grassland, cropland to wetlands) It is important to remember that those are suggested interpretations, and should be evaluated and adjusted considering the local conditions of the regions in for which the analysis will be performed. Land Cover Land cover: calculates land cover change relative to a baseline period, enter a transition matrix indicating which transitions indicate degradation, stability or improvement. Metadata: User enters unique task name and notes for the analyses. NDVI trend: This dataset shows the trend in annually integrated NDVI time series (2003-2015) using MODIS (250m) dataset (MOD13Q1) or AVHRR (8km; GIMMS3g.v1). The normalized difference vegetation index (NDVI) is the ratio of the difference between near-infrared band (NIR) and the red band (RED) and the sum of these two bands (Rouse et al., 1974; Deering 1978) and reviewed in Tucker (1979). NOTE: The valid date range is set by the NDVI dataset selected within the first tab: AVHRR dates compare 1982-2015 and MODIS 2001-2016. NOTE: This boundary should have only one polygon, i.e. when uploading a country with outlying islands, there will be multiple geometries drawn separately. By merging the polygons, the analysis will be run on the entire study area as opposed to a single polygon. Performance is a comparison of how productivity in an area compares to productivity in similar areas at the same point in time. Pixel RESTREND: The pointwise residual trend approach (P-RESTREND), attempts to adjust the NDVI signals from the effect of particular climatic drivers, such as rainfall or soil moisture, using a pixel-by-pixel linear regression on the NDVI time series and the climate signal, in this case precipitation from GCPC data at 250m resolution. The linear model and the climatic data is used then to predict NDVI, and to compute the residualsbetween the observed and climate-predicted NDVI annual integrals. The NDVI residual trend is finally plotted to spatially represent overall trends in primary productivity independent of climate. Productivity Productivity Performance Productivity State Productivity State assessments for each reporting period should compare the average of the annual productivity measurements over the reporting period (up to 4 years of new data) to the productivity classes calculated from the baseline period. NPP State classifications that have changed by two or more classes between the baseline and reporting period indicate significant productivity State change (CSIRO, 2017). Productivity Trajectory Productivity measures the trajectory, performance and state of primary productivity using either 8km GIMMS3g.v1 AVHRR or 250m MODIS datasets. The user can select one or multiple indicators to calculate, the NDVI dataset, name the tasks and enter in explanatory notes for their intended reporting area. Productivity: measures the trajectory, performance and state of primary productivity Rain use efficiency (RUE): is defined as the ratio between net primary production (NPP), or aboveground NPP (ANPP), and rainfall. It has been increasingly used to analyze the variability of vegetation production in arid and semi-arid biomes, where rainfall is a major limiting factor for plant growth Select NDVI dataset to use Select the baseline period of comparison. This determines the initial degradation state and serves as a comparison to assess change in degradation for each reporting period. Select the period of analysis. This determines the initial degradation state and serves as a comparison to assess change in degradation for each reporting period. Select which Indicator you would like to calculate Set up tab: Allows the user to select the starting year and ending year Soil Carbon Soil carbon: under review following the Good Practice Guidance `(UNCCD 2017) <http://www2.unccd.int/sites/default/files/relevant-links/2017-10/Good%20Practice%20Guidance_SDG%20Indicator%2015.3.1_Version%201.0.pdf>`_. Stable (land cover class remains the same over time period) State assessments for each reporting period should compare the average of the annual productivity measurements over the reporting period (up to 4 years of new data) to the productivity classes calculated from the baseline period. NPP State classifications that have changed by two or more classes between the baseline and reporting period indicate significant productivity State change (CSIRO, 2017). State is a comparison of how current productivity in an area compares to past productivity in that area. Sustainable Development Goal 15.3 intends to combat desertification, restore degraded land and soil, including land affected by desertification, drought and floods, and strive to achieve a land degradation-neutral world by 2030. In order to address this, we are measuring primary productivity, land cover and soil carbon to assess the annual change in degraded or desertified arable land (% of ha). The “Calculate indicators” button brings up a page that allows calculating datasets associated with the three SDG Target 15.3 sub indicators. For productivity and land cover, the toolbox implements the Tier 1 recommendations of the Good Practice Guidance lead by CSIRO. For productivity, users can calculate trajectory, performance, and state. For Land Cover, users can calculate land cover change relative to a baseline period, and enter a transition matrix indicating which transitions indicate degradation, stability, or improvement. The baseline period classifies annual productivity measurements to determine initial degradation. Pixels in the lowest 50% of classes may indicate degradation `(UNCCD 2017) <http://www2.unccd.int/sites/default/files/relevant-links/2017-10/Good%20Practice%20Guidance_SDG%20Indicator%2015.3.1_Version%201.0.pdf>`_. The baseline should be considered over an extended period over a single date (e.g. 1/1/2000-12/31/2015). The default for cropland to cropland is 0 because the land cover stays the same and is therefore stable. The default for forest to cropland is -1 because forest is likely cut to clear way for agriculture and would be considered deforestation. The final step before submitting the task to Google Earth Engine, is to define the study area on which to perform the analysis. The toolbox allows this task to be completed in one of two ways: The initial productivity performance is assessed in relation to the 90th percentile of annual productivity values calculated over the baseline period amongst pixels in the same land unit. Pixels with an NPP performance in the lowest 50% of the historical range may indicate degradation in this metric `(UNCCD 2017) <http://www2.unccd.int/sites/default/files/relevant-links/2017-10/Good%20Practice%20Guidance_SDG%20Indicator%2015.3.1_Version%201.0.pdf>`_. The initial productivity performance is assessed in relation to the 90th percentile of annual productivity values calculated over the baseline period amongst pixels in the same land unit. The toolbox defines land units as regions with the same combination of Global Agroecological Zones and land cover (300m from ESA CCI). Pixels with an NPP performance in the lowest 50% of the distribution for that particular unit may indicate degradation in this metric `(UNCCD 2017) <http://www2.unccd.int/sites/default/files/relevant-links/2017-10/Good%20Practice%20Guidance_SDG%20Indicator%2015.3.1_Version%201.0.pdf>`_. The initial trend is indicated by the slope of a linear regression fitted across annual productivity measurements over the entire period as assessed using the Mann-Kendall Z score where degradation occurs where z= ≤ -1.96 `(UNCCD 2017) <http://www2.unccd.int/sites/default/files/relevant-links/2017-10/Good%20Practice%20Guidance_SDG%20Indicator%2015.3.1_Version%201.0.pdf>`_. The major land cover change processes that are not considered degradation are: The starting year and end year will determine de period on which to perform the analysis. The transition can be defined as stable in terms of land degradation, or indicative of degradation (-1) or improvement (1). The user can upload a shapefile with an area of interest. The user selects first (i.e. country) and second (i.e. province or state) administrative boundary from a drop down menu. The user selects first (i.e. country) and second (i.e. province or state) administrative boundary from a drop-down menu. The user selects the baseline period and comparison period to determine the state for both existing and emerging degradation. To select the methods and datasets to calculate the indicators that measured changes in primary productivity, select the calculator icon (|iconCalculator|). This will open up the `Calculate Indicator` dialog box: Trajectory is related to the rate of change of productivity over time. Transition matrix tab Urban expansion (grassland, cropland wetlands or otherland to settlements) User selects target year. User selects the transition matrix value of land cover transitions for each transition between the 6 IPCC land cover classes. For example: Users can keep the default values or create unique transition values of their own. Users can select NDVI trends, Rain Use Efficiency (RUE), Pixel RESTREND or Water Use Efficiency (WUE) to determine the trends in productivity over the time period selected. Vegetation establishment (settlements or otherland to settlements) Vegetation loss (forest to grassland, otherland or grassland, cropland to other land) Water use efficiency (WUE):  refers to the ratio of water used in plant metabolism to water lost by the plant through transpiration. Wetland drainage (wetlands to cropland or grassland) Wetland establishment (settlements or otherland to wetlands) When all the parameters have been defined, click Calculate, and the task will be submitted to Google Earth Engine for computing. When the task is completed (processing time will vary depending on server usage, but for most countries it takes only a few minutes most of the time), you’ll receive an email notifying the successful completion. Withdrawal of agriculture (croplands to grassland) Withdrawal of settlements (settlements to otherland) Woody encroachment (wetlands to forest) Project-Id-Version: Land Degradation Monitoring Toolbox 1.0
Report-Msgid-Bugs-To: 
POT-Creation-Date: 2017-12-03 22:53-0500
PO-Revision-Date: YEAR-MO-DA HO:MI+ZONE
Last-Translator: Alex Zvoleff <azvoleff@conservation.org>, 2017
Language: sw
Language-Team: Swahili (https://www.transifex.com/conservation-international/teams/80165/sw/)
Plural-Forms: nplurals=2; plural=(n != 1)
MIME-Version: 1.0
Content-Type: text/plain; charset=utf-8
Content-Transfer-Encoding: 8bit
Generated-By: Babel 2.5.0
 **Calculating Land cover changes** **Calculating Performance** **Calculating State** **Calculating Trajectory** **Coming soon!** **Land cover - Area of interest** **Productivity - Area of interest** **Submit task** **Summary** Afforestation (grassland, cropland to forest; settlements to forest) Agricultural expansion (grassland to cropland; settlements or otherland to cropland) Assign a name to the task. Use descriptive names including study area, periods analyzed and datasets used, to be able to refer to them later. By default, and following the UNCCD best practices guidance document, the major land cover change processes that are classified as degradation are: Viashiria vya Hesabu Changes in land cover is one of the indicators used to track potential land degradation which need to be reported to the UNCCD and to track progress towards SDG 15.3.1. While some land cover transitions indicate, in most cases, processes of land degradation, the interpretation of those transitions are for the most part context specific. For that reason, this indicator requires the input of the user to identify which changes in land cover will be considered as degradation, improvement or no change in terms of degradation. The toolbox allows users to calculate land cover change relative to a baseline period, enter a transition matrix indicating which transitions indicate degradation, stability or improvement. Check next to Trajectory Click on the Calculate Indicators button from the toolbox bar, then select Land cover. Climate datasets need to be selected to perform climate corrections using RESTREND, Rain Use Efficiency or Water Use Efficiency (refer to table 1 for full list of climate variables available in the toolbox). Contemporary Productivity Performance for each reporting period should be calculated from an average of the years between the previous (or baseline) assessment up to the current year `(UNCCD 2017) <http://www2.unccd.int/sites/default/files/relevant-links/2017-10/Good%20Practice%20Guidance_SDG%20Indicator%2015.3.1_Version%201.0.pdf>`_. Deforestation (forest to cropland or settlements) Degradation in each reporting period should be assessed by appending the recent annual NPP values (measured in the toolbox as annual integral of NDVI) to the baseline data and calculating the trend and significance over the entire data series and the most recent 8 years of data `(UNCCD 2017) <http://www2.unccd.int/sites/default/files/relevant-links/2017-10/Good%20Practice%20Guidance_SDG%20Indicator%2015.3.1_Version%201.0.pdf>`_. In the tab “Trajectory”, select the method to be used to compute the productivity trajectory analysis. The options are: Inundation (forest, grassland, cropland to wetlands) It is important to remember that those are suggested interpretations, and should be evaluated and adjusted considering the local conditions of the regions in for which the analysis will be performed. Jalada la Ardhi Land cover: calculates land cover change relative to a baseline period, enter a transition matrix indicating which transitions indicate degradation, stability or improvement. Metadata: User enters unique task name and notes for the analyses. NDVI trend: This dataset shows the trend in annually integrated NDVI time series (2003-2015) using MODIS (250m) dataset (MOD13Q1) or AVHRR (8km; GIMMS3g.v1). The normalized difference vegetation index (NDVI) is the ratio of the difference between near-infrared band (NIR) and the red band (RED) and the sum of these two bands (Rouse et al., 1974; Deering 1978) and reviewed in Tucker (1979). NOTE: The valid date range is set by the NDVI dataset selected within the first tab: AVHRR dates compare 1982-2015 and MODIS 2001-2016. NOTE: This boundary should have only one polygon, i.e. when uploading a country with outlying islands, there will be multiple geometries drawn separately. By merging the polygons, the analysis will be run on the entire study area as opposed to a single polygon. Utendaji ni kulinganisha jinsi uzalishaji katika eneo kulinganisha na uzalishaji katika maeneo sawa katika hatua sawa kwa wakati. Pixel RESTREND: The pointwise residual trend approach (P-RESTREND), attempts to adjust the NDVI signals from the effect of particular climatic drivers, such as rainfall or soil moisture, using a pixel-by-pixel linear regression on the NDVI time series and the climate signal, in this case precipitation from GCPC data at 250m resolution. The linear model and the climatic data is used then to predict NDVI, and to compute the residualsbetween the observed and climate-predicted NDVI annual integrals. The NDVI residual trend is finally plotted to spatially represent overall trends in primary productivity independent of climate. Uzalishaji Productivity Performance Productivity State Productivity State assessments for each reporting period should compare the average of the annual productivity measurements over the reporting period (up to 4 years of new data) to the productivity classes calculated from the baseline period. NPP State classifications that have changed by two or more classes between the baseline and reporting period indicate significant productivity State change (CSIRO, 2017). Productivity Trajectory Productivity measures the trajectory, performance and state of primary productivity using either 8km GIMMS3g.v1 AVHRR or 250m MODIS datasets. The user can select one or multiple indicators to calculate, the NDVI dataset, name the tasks and enter in explanatory notes for their intended reporting area. Productivity: measures the trajectory, performance and state of primary productivity Rain use efficiency (RUE): is defined as the ratio between net primary production (NPP), or aboveground NPP (ANPP), and rainfall. It has been increasingly used to analyze the variability of vegetation production in arid and semi-arid biomes, where rainfall is a major limiting factor for plant growth Select NDVI dataset to use Select the baseline period of comparison. This determines the initial degradation state and serves as a comparison to assess change in degradation for each reporting period. Select the period of analysis. This determines the initial degradation state and serves as a comparison to assess change in degradation for each reporting period. Select which Indicator you would like to calculate Set up tab: Allows the user to select the starting year and ending year Chumvi ya Mchanga Soil carbon: under review following the Good Practice Guidance `(UNCCD 2017) <http://www2.unccd.int/sites/default/files/relevant-links/2017-10/Good%20Practice%20Guidance_SDG%20Indicator%2015.3.1_Version%201.0.pdf>`_. Stable (land cover class remains the same over time period) State assessments for each reporting period should compare the average of the annual productivity measurements over the reporting period (up to 4 years of new data) to the productivity classes calculated from the baseline period. NPP State classifications that have changed by two or more classes between the baseline and reporting period indicate significant productivity State change (CSIRO, 2017). Hali ni kulinganisha jinsi uzalishaji wa sasa katika eneo unalinganisha na uzalishaji wa zamani katika eneo hilo. Sustainable Development Goal 15.3 intends to combat desertification, restore degraded land and soil, including land affected by desertification, drought and floods, and strive to achieve a land degradation-neutral world by 2030. In order to address this, we are measuring primary productivity, land cover and soil carbon to assess the annual change in degraded or desertified arable land (% of ha). The “Calculate indicators” button brings up a page that allows calculating datasets associated with the three SDG Target 15.3 sub indicators. For productivity and land cover, the toolbox implements the Tier 1 recommendations of the Good Practice Guidance lead by CSIRO. For productivity, users can calculate trajectory, performance, and state. For Land Cover, users can calculate land cover change relative to a baseline period, and enter a transition matrix indicating which transitions indicate degradation, stability, or improvement. The baseline period classifies annual productivity measurements to determine initial degradation. Pixels in the lowest 50% of classes may indicate degradation `(UNCCD 2017) <http://www2.unccd.int/sites/default/files/relevant-links/2017-10/Good%20Practice%20Guidance_SDG%20Indicator%2015.3.1_Version%201.0.pdf>`_. The baseline should be considered over an extended period over a single date (e.g. 1/1/2000-12/31/2015). The default for cropland to cropland is 0 because the land cover stays the same and is therefore stable. The default for forest to cropland is -1 because forest is likely cut to clear way for agriculture and would be considered deforestation. The final step before submitting the task to Google Earth Engine, is to define the study area on which to perform the analysis. The toolbox allows this task to be completed in one of two ways: The initial productivity performance is assessed in relation to the 90th percentile of annual productivity values calculated over the baseline period amongst pixels in the same land unit. Pixels with an NPP performance in the lowest 50% of the historical range may indicate degradation in this metric `(UNCCD 2017) <http://www2.unccd.int/sites/default/files/relevant-links/2017-10/Good%20Practice%20Guidance_SDG%20Indicator%2015.3.1_Version%201.0.pdf>`_. The initial productivity performance is assessed in relation to the 90th percentile of annual productivity values calculated over the baseline period amongst pixels in the same land unit. The toolbox defines land units as regions with the same combination of Global Agroecological Zones and land cover (300m from ESA CCI). Pixels with an NPP performance in the lowest 50% of the distribution for that particular unit may indicate degradation in this metric `(UNCCD 2017) <http://www2.unccd.int/sites/default/files/relevant-links/2017-10/Good%20Practice%20Guidance_SDG%20Indicator%2015.3.1_Version%201.0.pdf>`_. The initial trend is indicated by the slope of a linear regression fitted across annual productivity measurements over the entire period as assessed using the Mann-Kendall Z score where degradation occurs where z= ≤ -1.96 `(UNCCD 2017) <http://www2.unccd.int/sites/default/files/relevant-links/2017-10/Good%20Practice%20Guidance_SDG%20Indicator%2015.3.1_Version%201.0.pdf>`_. The major land cover change processes that are not considered degradation are: The starting year and end year will determine de period on which to perform the analysis. The transition can be defined as stable in terms of land degradation, or indicative of degradation (-1) or improvement (1). The user can upload a shapefile with an area of interest. The user selects first (i.e. country) and second (i.e. province or state) administrative boundary from a drop down menu. The user selects first (i.e. country) and second (i.e. province or state) administrative boundary from a drop-down menu. The user selects the baseline period and comparison period to determine the state for both existing and emerging degradation. To select the methods and datasets to calculate the indicators that measured changes in primary productivity, select the calculator icon (|iconCalculator|). This will open up the `Calculate Indicator` dialog box: Trajectory is related to the rate of change of productivity over time. Transition matrix tab Urban expansion (grassland, cropland wetlands or otherland to settlements) User selects target year. User selects the transition matrix value of land cover transitions for each transition between the 6 IPCC land cover classes. For example: Users can keep the default values or create unique transition values of their own. Users can select NDVI trends, Rain Use Efficiency (RUE), Pixel RESTREND or Water Use Efficiency (WUE) to determine the trends in productivity over the time period selected. Vegetation establishment (settlements or otherland to settlements) Vegetation loss (forest to grassland, otherland or grassland, cropland to other land) Water use efficiency (WUE):  refers to the ratio of water used in plant metabolism to water lost by the plant through transpiration. Wetland drainage (wetlands to cropland or grassland) Wetland establishment (settlements or otherland to wetlands) When all the parameters have been defined, click Calculate, and the task will be submitted to Google Earth Engine for computing. When the task is completed (processing time will vary depending on server usage, but for most countries it takes only a few minutes most of the time), you’ll receive an email notifying the successful completion. Withdrawal of agriculture (croplands to grassland) Withdrawal of settlements (settlements to otherland) Woody encroachment (wetlands to forest) 