.. _1-step_subindicators:

Run 1-step subindicators
========================

- **Objective**: Learn to run SDG 15.3.1 sub-indicators (changes in land productivity, land cover and soil organic carbon) using Trends.Earth and the default data: LPD from JRC for land productivity, ESA CCI for land cover, and SoilGrids for soil organic carbon. In this tutorial we will use Uganda as an example, but you can choose any study area.

- **Estimated time of completion**: 20 minutes

- **Internet access**: Required

.. note:: `Download this page as a PDF for off-line use 
   <../pdfs/Trends.Earth_Tutorial03_Computing_Indicators.pdf>`_

1. Search for the Trends.Earth toolbar (shown below) within QGIS, and click on the Calculate icon (|iconCalculator|).
   
.. image:: /static/common/ldmt_toolbar_highlight_calculate.png
   :align: center   

2. The **Calculate Indicators** menu will open. In that window, click on **Calculate all three sub-indicators in one step** button found under option 1 of step 1.

.. image:: /static/training/t03/run.png
   :align: center

3. In the **Setup** tab, select the years of analysis (2000-2015) and make sure that the **UNCCD default data** is selected, and click next.

.. note::
    Refer to the :ref:`indicator-15-3-1` section of this manual to learn about the Trends.Earth productivity indicators developed following the `UNCCD Good Practice Guidance (GPG) <http://www2.unccd.int/sites/default/files/relevant-links/2017-10/Good%20Practice%20Guidance_SDG%20Indicator%2015.3.1_Version%201.0.pdf>`_.
 
.. image:: /static/training/t03/run_setup.png
   :align: center

4. In the **Land Cover Setup** tab you have the option of using the default aggregation method proposed by the UNCCD default data or you can customize the aggregation of the legend from the original ESA CCI land cover classes to the 7 required for UNCCD reporting. To customize it, click on **Edit definition** and the **Setup aggregation of land cover data** window will open.

.. image:: /static/training/t03/run_landcover.png
   :align: center

5. In this window you will see the original ESA CCI land cover class in the column **Input class** and the final aggregation in the column **Output class**. To change the output class simply click in the drop down arrow next to the color, and select the final output class you want the input class to be reassigned to. Note that this step is only needed if you consider that the default aggregation scheme does not represent the conditions of your study area.

 When you are done editing, click **Save definition file**. This option will save you time next time you run the tool, by simply loading the definition file you previously saved.

 Click **Save** to continue   
   
.. image:: /static/training/t03/run_landcover_aggr.png
   :align: center

6. You will be back at the **Land Cover Setup** tab, click **Next**.
   
.. image:: /static/training/t03/run_landcover.png
   :align: center   

7. The **Define Effects of Land Cover Change** tab is where you define the meaning of each land cover transition in terms of degradation. Transitions indicated in red (minus sign) will be identified as degradation in the final output, transitions in beige (zero) will be identified as stable, and transitions in green (plus sign) will be identified as improvements. 

 For example, by default it is considered that a pixel that changed from **Grassland** to **Tree-covered** will be considered as improved. However, if in your study area woody plant encroachment is a degradation process, that transition should be changed for that particular study area to degradation (minus sign).

 If you have made no changes to the default matrix, simply click **Next**.

 If you did change the meaning of some of the transitions, click on **Save table to file...** to save the definition for later use. Then click **Next**.
   
.. image:: /static/training/t03/run_landcover_degr.png
   :align: center

8. In the **Area** tab define the area of analysis. There are two options:

 - Use provided country and state boundaries: If you want to use this option make sure the **Administrative area** option is highlighted, and then select the First Level (country) or Second Level (state or province depending on the country).

.. note::
    The `Natural Earth Administrative Boundaries`_ provided in Trends.Earth, 
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
 
 When you have selected the area for which you want to compute the indicators, click **Next**.
   
.. image:: /static/training/t03/run_area.png
   :align: center

9. In the **Options** tab you can define the **Task name** and make some **Notes** to identify the analysis you are running. What information to indicate is optional, but we suggest noting:

 - Area of analysis
 - Dates
 - Indicators run

10. When done, click **Calculate** and the task will be submitted to Google Earth Engine for calculations. You will notice that the **Calculate SDG 15.3.1 indicator (one-step)** window will disappear and you will be brought back to QGIS.

.. image:: /static/training/t03/run_options.png
   :align: center
   
11. A light blue bar (as shown in the image below) will temporarily show, indicating that the task was successfully submitted. The analysis will be run in Google servers and could take between 5 and 15 minutes depending on the size of the study area (larger areas tend to take longer).

.. image:: /static/training/t03/submitted.png
   :align: center   

.. note::
    Refer to the :ref:`task_download` tutorial for instructions on how to check the status of the tasks submitted and for downloading results from Trends.Earth.
