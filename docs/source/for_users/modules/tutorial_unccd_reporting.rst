.. _unccd_reporting:

Reporting to the UNCCD
========================

- **Objective**: Learn how to run SDG 15.3.1 sub-indicators (changes in land productivity, land cover and soil organic carbon) using Trends.Earth and the UNCCD default data: LPD from JRC for land productivity, ESA CCI for land cover, and SoilGrids for soil organic carbon. In this tutorial we will use Uganda as an example, but you can choose any study area.

- **Estimated time of completion**: 35 minutes

- **Internet access**: Required

.. note:: `Download this page as a PDF for off-line use 
   <../pdfs/Trends.Earth_Tutorial02_Computing_Indicators.pdf>`_

1. Click on the Trends.Earth toolbar within QGIS, and click on the Trends.Earth icon (|icon-trends_earth|).
   
.. image:: /static/common/icon-trends_earth_selection.png
   :align: center   

2. The **Trends.Earth** menu will open. In the **Algorithm** window, click on **UNCCD Reporting - Summarize data for reporting**

.. image:: /static/documentation/calculate/unccd_reporting_module.png
   :align: center

Select **Execute remotely** button.

3. In the **Calculate default datasets for UNCCD reporting** tab you can define the **Execution name** and make some **Notes** to identify the analysis you are running. What information to indicate is optional, but we suggest noting:

 - Area of analysis
 - Dates for baseline and progress period

Select **Schedule remote execution** button.

4. Click the **Datasets** tab and the progress (running in Google Earth Engine) will display. When complete it will appear in the **Datasets** tab, where you can select the dropdown to add to map.

.. image:: /static/documentation/calculate/unccd_reporting_running.png
   :align: center
   
5. To complete reporting, select the **Algorithm** window, click on **UNCCD Reporting - Summarize data for reporting**

Select **Execute locally** button. A window will appear

6. In the **SDG 15.3.1 Indicator (Summary) Land Degradation** window, select the datasets for Strategic Objective (SO) 1 and 2, Objective 3 (tires 1 and 2) and 2 (tier 3) (if available), enter your **Execution name** and some **Notes**. 

Select **Execute locally** button.

.. image:: /static/documentation/calculate/unccd_reporting_final.png
   :align: center
   
.. note::
    Refer to the :ref:`task_download` tutorial for instructions on how to check the status of the tasks submitted and for downloading results from Trends.Earth.
