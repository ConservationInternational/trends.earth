.. _tut_forest_carbon:

Forest and Carbon Change Tool
=============================

- **Objective**: Learn how to compute forest cover, forest loss, above and below ground biomass and emissions from deforestation in raster format and tabular outputs with areas estimated.

- **Estimated time of completion**: 20 minutes

- **Internet access**: Required

.. note:: `Download this page as a PDF for offline use 
   <../pdfs/Trends.Earth_Tutorial10_Forest_Carbon.pdf>`_

.. _compute_forest_data:

Compute and download forest and biomass data
--------------------------------------------   
   
1.	Select the Calculate icon (|iconCalculator|) from the Trends.Earth plugin in QGIS.

.. image:: /static/common/ldmt_toolbar_highlight_calculate.png
   :align: center   

2. The **Calculate Indicators** menu will open. In that window, click on **Calculate Calculate carbon change spatial layers** button.

.. image:: /static/training/t11/calc_ind.png
   :align: center
   
3. A window will appear with two steps: Step 1 is to **Calculate carbon change spatial layers**, and Step 2 is to **Calculate carbon change summary table for boundary**. Step 1 will be addressed first. If the user has already completed this process, skip to step 14 in the guide.

.. image:: /static/training/t11/calc_carbon.png
   :align: center

4. After selecting Step 1, the user will fill out the desired parameters in the **Forest Definition** tab.

.. image:: /static/training/t11/forest_def.png
   :align: center
   
5. Next, select the desired aboveground biomass dataset and the method for calculating the root to shoot ratio.

.. image:: /static/training/t11/carbon_method.png
   :align: center
   
6. In the **Area** tab define the area of analysis. There are two options:

 - Use provided country and state boundaries: If you want to use this option make sure the **Administrative area** option is highlighted, and then select the First Level (country) or Second Level (state or province depending on the country).

.. note::
    The `Natural Earth Administrative Boundaries`_ provided in Trends.Earth 
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
   
.. image:: /static/training/t11/area_uganda.png
   :align: center

7. In the **Options** tab you can define the **Task name** and make some **Notes** to identify the analysis you are running. What information to indicate is optional, but we suggest noting:

 - Area of analysis
 - Dates
 - Indicators run
   
.. image:: /static/training/t11/options.png
   :align: center 

8. When done, click **Calculate** and the task will be submitted to Google Earth Engine for calculations. You will notice that the **Calculate Change in Total Carbon** window will disappear and you will be brought back to QGIS.

9. A light blue bar will temporarily show, indicating that the task was successfully submitted. The analysis will be run in Google servers and could take between 5 and 15 minutes depending on the size of the study area (larger areas tend to take longer).

.. image:: /static/training/t11/submit_carbon.png
   :align: center   

.. note::
    Refer to the :ref:`task_download` tutorial for detailed information on how to check the status of the tasks submitted and for downloading results from Trends.Earth.

.. image:: /static/common/ldmt_toolbar_highlight_tasks.png
   :align: center

10. To view the Google Earth Engine (GEE) tasks you have running, and to download your results, select 
the cloud with the arrow facing down icon (|iconCloudDownload|). This will open up the `Download results 
from Earth Engine` dialog box. Select **Refresh list** to show the task.
 
.. image:: /static/training/t11/running.png
   :align: center 

11. The task will state: RUNNING under the Status column if it is still processing. When the task is complete, it will say FINISHED after selecting **Refresh List** again. 

.. image:: /static/training/t11/finished.png
   :align: center 

Once the task is FINSHED running, highlight the completed task and select **Download Results**. Save the task.

.. image:: /static/training/t11/save.png
   :align: center 
   
13. You will see a message indicating the task is downloading. Once it is complete there will be a `Total carbon (2000, tonnes per ha)` and `Forest loss (2000 to 2017)` outputs in the QGIS window.

.. image:: /static/training/t11/download.png
   :align: center 

.. image:: /static/training/t11/total_carbon.png
   :align: center

.. image:: /static/training/t11/forest_loss.png
   :align: center

If you want, you can add some context information (e.g. country boundaries, roads, and main cities). Refer to the :ref:`tut_load_data` tutorial for detailed information on loading a basemap.

.. _compute_forest_summary:

Compute summary table
---------------------  
   
1.	Select the Calculate icon (|iconCalculator|) from the Trends.Earth plugin in QGIS.

.. image:: /static/common/ldmt_toolbar_highlight_calculate.png
   :align: center   

2. The **Calculate Indicators** menu will open. In that window, click on **Calculate Calculate carbon change spatial layers** button.

.. image:: /static/training/t11/calc_ind.png
   :align: center
   
3. Select Step 2: **Calculate carbon change summary table for boundary**. 

.. image:: /static/training/t11/carbon_change.png
   :align: center

4. Within the **Input** tab, select an output folder and file name.

.. image:: /static/training/t11/input.png
   :align: center

5. Within the **Output** tab, select **Browse** to list an output folder and file name.

.. image:: /static/training/t11/output.png
   :align: center
   
6. In the **Area** tab define the area of analysis. There are two options:

 - Use provided country and state boundaries: If you want to use this option make sure the **Administrative area** option is highlighted, and then select the First Level (country) or Second Level (state or province depending on the country).

 - Use your own area file: If you want to use your own area of analysis, make sure the **Area from file** option is highlighted. Then click **Browse** and navigate to the folder in your computer where you have the file stored. 
 
 When you have selected the area for which you want to compute the indicators, click **Next**.   
   
.. image:: /static/training/t11/area_uganda.png
   :align: center

7. In the **Options** tab you can define the **Task name** and make some **Notes** to identify the analysis you are running. What information to indicate is optional, but we suggest noting:

 - Area of analysis
 - Dates
 - Indicators run
   
.. image:: /static/training/t11/uganda_carbon_change.png
   :align: center 

8. When done, click **Calculate** and the task will be submitted to your computer locally. You will notice that the **Calculate carbon change summary table for boundary** window will disappear and you will be brought back to QGIS. A light blue bar will appear in the QGIS window. This is running locally on your computer. DO NOT select **x** or **Cancel** until the task is finished!

.. image:: /static/training/t11/summary_submit.png
   :align: center
   
9. A window will appear when the summary is complete. Select **OK**.

.. image:: /static/training/t11/success.png
   :align: center   

10. If an error window appears, select the **Yes** and the summary will proceed to open.

.. image:: /static/training/t11/error.png
   :align: center   
   
11. The summary table will appear.

.. image:: /static/training/t11/summary_table.png
   :align: center   
