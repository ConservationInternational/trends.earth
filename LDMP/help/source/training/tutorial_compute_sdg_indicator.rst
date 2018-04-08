.. _tut_compute_sdg:

Compute SDG indicator
======================

- **Objective**: Learn to integrate the land cover, primary productivity and soil organic carbon sub-indicators to compute SDG 15.3.1 in raster format and tabular outputs with areas estimated.

- **Estimated time of completion**: 20 minutes

- **Internet access**: Not required

.. note:: `Download this page as a PDF for offline use 
   <../pdfs/Trends.Earth_Tutorial08_Computing_SDG_Indicator.pdf>`_

.. note::
    You will need to have previously computed the land cover, soil organic carbon and land productivity indicators prior to running this tool. If you have not, please refer to the following specific tutorials to compute them: :ref:`1-step_subindicators`, :ref:`tut_custom_lc`, :ref:`tut_custom_lpd`, and :ref:`tut_custom_soc`.

1. Search for the Trends.Earth toolbar within QGIS, and click on the Calculate icon (|iconCalculator|).
   
.. image:: /static/common/ldmt_toolbar_highlight_calculate.png
   :align: center   

2. The **Calculate Indicators** menu will open. In that window, click on **Calculate final SDG 15.3.1 spatial layer and summary table for total boundary** button found under Step 2 - Option 1.

.. image:: /static/training/t05/calculate_sdg.png
   :align: center

3. In the **Input** tab you will select each of the input layers needed for computing the final SDG 15.3.1. You ave the option of using **Trends.Earth land productivity** or **UNCCD default data**. In this case select UNCCD default data.

.. note::
    Refer to the :ref:`indicator-15-3-1` section of this manual to learn about the Trends.Earth productivity indicators developed following the `UNCCD Good Practice Guidance (GPG) <http://www2.unccd.int/sites/default/files/relevant-links/2017-10/Good%20Practice%20Guidance_SDG%20Indicator%2015.3.1_Version%201.0.pdf>`_.
   
4. If you have the sub-indicators loaded into the QGIS map, the tool will recognize them and they will show up pre-filled in each corresponding section.

.. note::
	If you have more than one layer loaded into the map per sub-indicator (for example, land cover change computed with default and also with custom data) make sure to check that the one being used to compute the final SDG is the one you want.

5. If the sub-indicators are not loaded in your QGIS map, then click **Load existing** next to each of the sub-indicators sections, and nagivate to the folder where you stored them in your computer.
 
 When done selecting inputs, click **Next**.
   
.. image:: /static/training/t05/sdg_input.png
   :align: center

6. In the **Output** tab you will need to define the name and location for the final **SDG 15.3.1 indicator** and the **summary table**. Click **Browse** next to each of them to select the output location and to define names. 
   
.. image:: /static/training/t05/sdg_output1.png
   :align: center

7. When done, click **Next**.
   
.. image:: /static/training/t05/sdg_output4.png
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
   
.. image:: /static/training/t05/sdg_area.png
   :align: center

9. In the **Options** tab you can define the **Task name** and make some **Notes** to identify the analysis you are running. What information to indicate is optional, but we suggest noting:

 - Area of analysis
 - Dates
 - Indicators run   
   
.. image:: /static/training/t05/sdg_options.png
   :align: center

10. When done, click **Calculate**. A light blue bar will temporarily show, indicating that the task was successfully submitted. 

.. note:: This analysis will be run in your local computer, so the processing time will depend on the size of the area, resolution of the data, and the processing capabilities of your computer. Do not close your computer or put it to sleep while running, because the analysis will fail.
   
.. image:: /static/training/t05/sdg_computing.png
   :align: center

11. When the analysis is completed a **Success** message will notify you and the indicator will be loaded to the map.   
   
.. image:: /static/training/t05/sdg_success.png
   :align: center

.. image:: /static/training/t05/sdg_indicator.png
   :align: center

.. note::
    Refer to the :ref:`tut_interpret_table` section of this manual to learn how to open and interpret the information in the summary table created by this analysis.   
   