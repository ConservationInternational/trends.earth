Run 1-step subindicators
========================

- **Objective**: Learn to run SDG 15.3.1 sub-indicators (changes in land productivity, land cover and soil organic carbon) using Trends.Earth and the default data (LPD from JRC for land productivity, ESA CCI for land cover, and SoilGrids for soil organic carbon). 

- **Estimated time of completion**: 20 minutes

- **Internet access**: Required

.. note:: `Download this page as a PDF for offline use 
   <../pdfs/Trends.Earth_Tutorial03_Computing_Indicators.pdf>`_

1. Search for the Trends.Earth toolbar (shown below) within QGIS, and click on the calculator icon (ADD ICON).
   
.. image:: /static/common/ldmt_toolbar_highlight_calculate.png
   :align: center   

2. The **Calculate Indicators** menu will open. In that window, click on **Calculate all three sub-indicators in one step** button found under option 1 of step 1.

.. image:: /static/training/t03/run.png
   :align: center

3. In the **Setup** window, select the years of analysis (2000-2015 as default) and make sure that the **UNCCD default data is loaded**, and click next.

 Note: If interested in learning more about the Trends.Earth productivity indicators refer to XXXXXX. 
   
.. image:: /static/training/t03/run_setup.png
   :align: center

4. In the **Land Cover Setup window** you have the option of using the default aggregation method proposed by the UNCCD default data or you can customize the aggregation of the legend from the original ESA CCI land cover classes to the 7 required for UNCCD reporting. To customize it, click on **Edit definition** and the **Setup aggregation of land cover data** window will open.

.. image:: /static/training/t03/run_landcover.png
   :align: center

5. In this window you will see the original ESA CCI land cover class in the column **Input class** and the final aggregation in the column **Output class**. To change the output class simply click in the drop down arrow next to the color, and select the final output class you want the input class to be reassigned to. Note that this step is only needed if you consider that the default aggregation scheme does not represent the conditions of your study area.

 When you are done editing, click **Save definition file**. This option will save you time next time you run the tool, by simply loading the definition file you previously saved.

 Click **Save** to continue   
   
.. image:: /static/training/t03/run_landcover_aggr.png
   :align: center

6. You will be back at the **Land Cover Setup window**, click **Next**.
   
.. image:: /static/training/t03/run_landcover.png
   :align: center   

7. The **Define Effects of Land Cover Change** window is where you define the meaning of each land cover transition in terms of degradation. Transitions indicated in red (minus sign) will be identified as degradation in the final output, transitions in beige (zero) will be identified as stable, and transitions in green (plus sign) will be identified as improvements. 

 For example, by default it is considered that a pixel that changed from **Grassland** to **Tree-covered** will be considered as improved. However, if in your study area woody plant encroachment is a degradation process, that transition should be changed for that particular study area to degradation (minus sign).

 If you have made no changes to the default matrix, simply click **Next**.

 If you did change the meaning of some of the transitions, click on **Save table to file..** to save the definition for later use. Then click **Next**.
   
.. image:: /static/training/t03/run_landcover_degr.png
   :align: center

8. In the **Area** window define the area of analysis. There are two options here:

 - Use provided country and state boundaries: If you want to use this option make sure the **Administrative area** option is highlighted, and then select the First Level (country) or Second Level (state or province depending on the country).

(ADD DISCLAIMER).

 - Use your own area file: If you want to use your own area of analysis, make sure the **Area from file** option is highlighted. Then click **Browse** and navigate to the folder in your computer where you have the file stored. When done, click **Next**.
   
.. image:: /static/training/t03/run_area.png
   :align: center

9. In this window use the **Task name** and **Notes** field to identify the analysis you are running. What information to note is personal, but we suggest noting:

 - Area of analysis
 - Dates
 - Indicators run
 - Options changed   

 When done, click **Calculate** and the task will be submitted to Google Earth Engine for calculations.

 You will notice that the **Calculate SDG 15.3.1 indicator (one-step)** window will disappear and you will be brought back to QGIS.

.. image:: /static/training/t03/run_options.png
   :align: center
   
10. A light blue bar (as shown in the image below) will temporarily show, indicating that the task was successfully submitted. The analysis will be run in Google servers and could take ~5-10 minutes depending on the size of the study area (larger areas tend to take longer).

 If you get an error bar, make sure that your computer has Internet access, since that will be required for submitting the task.
   
.. image:: /static/training/t03/submitted.png
   :align: center   

11. To check the status of the task, click on the Cloud icon (ADD NAME and ICON) in the trends.Earth toolbar, and the **Download results from Earth Engine**  window will open. 
   
.. image:: /static/common/ldmt_toolbar_highlight_tasks.png
   :align: center   
   
12. The first time you open this window, no task will be displayed. To check the status of submitted tasks, click on **Refresh list**. After a few seconds the tasks submitted will be shown. 

13. Check the **Status** column. One of three messages will show there:

 - **RUNNING**: The task has been successfully submitted to Earth Engine and it is being processed. Wait a few minutes and click **Refresh list** again.

 - **FINISHED**: The task has been completed and it is ready to be downloaded.

 - **FAILED**: There has been some error in the parameters selected and the task could not be completed. Please run the tool again to make sure all parameters are correct.

.. image:: /static/training/t03/running.png
   :align: center
   
REFER TO NEXT TUTORIAL