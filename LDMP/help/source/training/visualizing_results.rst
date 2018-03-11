Visualizing results in QGIS
===========================

To select the methods and datasets to calculate the indicators that measured changes in primary productivity, select the calculator icon (|iconCalculator|). 
This will open up the `Calculate Indicator` dialog box:
   
.. image:: /static/common/ldmt_toolbar_highlight_calculate.png
   :align: center

**Summary**
   
Sustainable Development Goal 15.3 intends to combat desertification, restore degraded land and soil, including land affected by desertification, drought and floods, and strive to achieve a land degradation-neutral world by 2030. In order to address this, we are measuring primary productivity, land cover and soil carbon to assess the annual change in degraded or desertified arable land (% area or km²). The `Calculate indicators` button brings up a page that allows calculating datasets associated with the three SDG Target 15.3 sub indicators. For productivity and land cover, the toolbox implements the Tier 1 recommendations of the Good Practice Guidance lead by CSIRO and UNCCD. For productivity, users can calculate trajectory, performance, and state. For Land Cover, users can calculate land cover change relative to a baseline period, and enter a transition matrix indicating which transitions indicate degradation, stability, or improvement.

There are several options for calculating the SDG 15.3.1 Indicator:

Step 1: Prepare sub-indicators
Option 1: Use default UNCCD data

or

Option 2: Customize data
Select which Indicator you would like to calculate

•	Productivity: measures the trajectory, performance and state of primary productivity

•	Land cover: calculates land cover change relative to a baseline period, enter a transition matrix indicating which transitions indicate degradation, stability or improvement.

•	Soil carbon: under review following the Good Practice Guidance `(UNCCD 2017) <http://www2.unccd.int/sites/default/files/relevant-links/2017-10/Good%20Practice%20Guidance_SDG%20Indicator%2015.3.1_Version%201.0.pdf>`_.

Step 2: Calculate final SDG 15.3.1 indicator and summary table

.. image:: /static/documentation/calculate/image021.png
   :align: center

Step 1: Prepare sub-indicators
------------------------------

Option 1: Use default UNCCD data
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
**Summary**
This allows users to calculate all three sub-indicators in one step. Select the Calculate all three sub-indicators in one step button

Select the parameters for Setup. The Period is the Initial and Final year for the analysis and select one of the two Land Productivity datasets. Select Next.

.. image:: /static/documentation/calculate/image022.png
   :align: center
   
Select the Land Cover dataset. The first option is the default ESA dataset.

.. image:: /static/documentation/calculate/image023.png
   :align: center

Select Edit definition to change the aggregation from the ESA Land Cover dataset into 7 classes.

.. image:: /static/documentation/calculate/image024.png
   :align: center

The second option allows users to upload a custom land cover dataset. This requires two datasets to compare change over time. Select Next.
The user can now define the effects of land cover change and how it is classified as degrading or improving.

.. image:: /static/documentation/calculate/image025.png
   :align: center

Select an area to run the analysis or upload a shapefile boundary

.. image:: /static/documentation/calculate/image026.png
   :align: center

Name the task and make notes for future reference   

.. image:: /static/documentation/calculate/image027.png
   :align: center
   
Option 2: Customize data
   Visualizing results from Productivity 

.. image:: /static/training/visualizing_results/image028.png
   :align: center

.. image:: /static/training/visualizing_results/image029.png
   :align: center

.. image:: /static/training/visualizing_results/image030.png
   :align: center

.. image:: /static/training/visualizing_results/image031.png
   :align: center

.. image:: /static/training/visualizing_results/image032.png
   :align: center

Visualizing results from Land Cover Change
Parameters used:

.. image:: /static/training/visualizing_results/image033.png
   :align: center

.. image:: /static/training/visualizing_results/image034.png
   :align: center
   
.. image:: /static/training/visualizing_results/image035.png
   :align: center
   
.. image:: /static/training/visualizing_results/image036.png
   :align: center
   
.. image:: /static/training/visualizing_results/image037.png
   :align: center
   
.. image:: /static/training/visualizing_results/image038.png
   :align: center
   
Visualizing results from Soil organic carbon
Parameters used:

.. image:: /static/training/visualizing_results/image039.png
   :align: center

.. image:: /static/training/visualizing_results/image040.png
   :align: center
   
.. image:: /static/training/visualizing_results/image041.png
   :align: center
   
.. image:: /static/training/visualizing_results/image042.png
   :align: center
   
.. image:: /static/training/visualizing_results/image043.png
   :align: center
 
Visualizing results from final SDG 15.3.1 indicator and summary table
 
.. image:: /static/training/visualizing_results/image044.png
   :align: center

.. image:: /static/training/visualizing_results/image045.png
   :align: center
   
.. image:: /static/training/visualizing_results/image046.png
   :align: center
   
.. image:: /static/training/visualizing_results/image047.png
   :align: center
   
.. image:: /static/training/visualizing_results/image048.png
   :align: center
   
The output of these analyses and tips for understanding these results can be found in the `Interpreting Results` section.