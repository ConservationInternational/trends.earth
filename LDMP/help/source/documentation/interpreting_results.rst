Interpreting Results
==================================
The three metrics (trend, state and performance) are aggregated to determine if land is degraded in 
areas where productivity may be increasing but remains low relative to other areas with similar 
land cover characteristics and climatic conditions. Areas with a statistically significant negative 
trend over time indicate a decline in productivity. When both performance and state show potential 
degradation, the assessment indicates negative productivity as well. trends.earth allows users to 
select the trajectory indicatory method to detect productivity. Selecting NDVI Trends for the 
baseline period 2001-2016 will yield the following two outputs:
   
.. image:: /static/documentation/interpreting_results/image071.png
   :align: center

(left) Productivity trajectory trend (significance) and (right) Productivity trajectory trend 
(slope of NDVI) for East Africa and Senegal.
	
.. image:: /static/documentation/interpreting_results/image072.png
   :align: center
   
Performance is a measurement of local productivity relative to other similar vegetation types in 
similar land cover types and bioclimatic regions (areas of similar topographic, edaphic and 
climatic conditions). The initial baseline value for land productivity, from which future changes 
are compared, is 2001-2015 in the above performance output.
	
.. image:: /static/documentation/interpreting_results/image073.png
   :align: center

State compares the current productivity level in a given area to historical observations of 
productivity in that same area. Assessments are completed for a given location over time, as an 
indicator of the current state of vegetation productivity. These three-metrics help determine if 
land is degraded in areas where productivity may be increasing but remains low relative to other areas with similar land cover characteristics and climatic conditions. In this assessment, 
changes in productivity are considered negative when there is a statistically significant negative 
trend over time, or when both the Performance and State assessments indicate potential degradation, 
including in areas where the trend is not significantly negative (CSIRO 2017).
	
.. image:: /static/documentation/interpreting_results/image074.png
   :align: center

In order to interpret the likelihood of results indicating false positives or false negatives, a 
lookup table is used to identify ‘support class’ combinations of metrics in each pixel (CSIRO 2017). 
Classes 1-5 indicate degradation.
	
.. image:: /static/documentation/interpreting_results/image075.png
   :align: center

The assessment and evaluation of land cover changes are derived from the European Space Agency Climate 
Change Initiative Land Cover (ESA-CCI-LC) 300m product. These are aggregated into the IPCC major 
land cover classes: Forest land, grassland, cropland, wetlands, settlements and other land. 
Degradation can be identified through land cover as: 1) a decline in the productive capacity of 
the land, through loss of biomass or a reduction in vegetation cover and soil nutrients, 2) a 
reduction in the land’s capacity to provide resources for human livelihoods, 3) a loss of 
biodiversity or ecosystem complexity, and 4) an increased vulnerability of population or 
habitats to destruction at the national scale (CSIRO 2017).

.. image:: /static/documentation/interpreting_results/image076.png
   :align: center

Land cover transitions are designated by the user via the transition matrix. This example, using 
the default in trends.earth, the beige color indicate areas where no change has occurred. The 
remaining pixels highlighted demonstrate the transition from the baseline (2000-2014) to the 
target year (2015). A closer look (below) shows transitions in central Tanzania of conversion 
from croplands (red) or forest land (green) to other land cover classes.

.. image:: /static/documentation/interpreting_results/image077.png
   :align: center

.. image:: /static/documentation/interpreting_results/image078.png
   :align: center

The transition matrix has both default values and the option to select the transition values 
within the context of the specified area of interest. The matrix allows users to define 30 
possible transitions. The unlikely transitions are highlighted above (left) in red text with 
major land cover processed (flows) noted. The boxes are color coded as improvement (green), 
stable (blue) or degradation (red) using land cover/land use change for the 6 IPCC classes 
(CSIRO 2017). The table (above right) demonstrates how the description of major land cover 
change processes are identified as flows. Note that some transitions between classes will not 
yield logical results.

.. image:: /static/documentation/interpreting_results/image079.png
   :align: center

Calculating the final indicator is done using the pie chart symbol in trends.earth. The output layer 
can be selected using the existing layers within the map: Productivity trajectory trend 
(significance), productivity performance (degradation), Productivity (emerging) and Land Cover 
(degradation). These are aggregated to highlight degradation given the inputs and parameters 
from former analyses.

.. image:: /static/documentation/interpreting_results/image081.png
   :align: center

The final output show degradation in red and improvement in green excluding the urban and water 
values from the output. Given the analyses prior to the we can conclude that the areas in red 
have been degraded using 2001-2016 as a baseline for NDVI Trend (trajectory), 2001-2015 for 
performance, 2001-2015 for emerging baseline with 2015 as the target year of comparison for 
degradation. Land cover highlighted the transition from the baseline (2000-2014) to the target 
year (2015) using the standard default transitions to identify degradation. Together these were 
aggredated to forumulate the final degradation output above. This notes degradation within 
central Uganda.
