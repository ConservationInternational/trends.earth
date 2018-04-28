.. _tut_custom_lc:

Use custom land cover data
==========================

- **Objective**: Learn how to load custom land cover data and to compute the land cover change sub-indicator using Trends.Earth.

- **Estimated time of completion**: 40 minutes

- **Internet access**: Not required

.. note:: `Download this page as a PDF for offline use 
   <../pdfs/Trends.Earth_Tutorial05_Using_Custom_Land_Cover.pdf>`_

.. note:: The land cover dataset for this tutorial were provided by the `Regional Centre For Mapping Resource For Development <http://geoportal.rcmrd.org/layers/servir%3Auganda_landcover_2014_scheme_i>`_ and can be downloaded from this `link <https://www.dropbox.com/s/rl8afjh7xhnhk5a/uganda_land_cover.zip?dl=0>`_.
   

1. To load custom land cover data click on the (|iconfolder|) icon in the Trends.Earth toolbar.

.. image:: /static/common/ldmt_toolbar_highlight_loaddata.png
   :align: center

2. The **Load data** menu will open. Select **Land cover** from the **Import a custom input dataset** section.
	
.. image:: /static/training/t08/custom_landcover.png
   :align: center

3. In the **Load a Custom Land Cover dataset** use the radio button to select the format of the input file (raster or vector). For this tutorial select raster, but you could run it with your land cover vector data if you prefer. Click on **Browse** to navigate to the land cover file you wish to import. 
   
.. image:: /static/training/t08/custom_landcover_menu1.png
   :align: center

4. Use the **Select input file** window to navigate to the file to be imported, select it, and click **Open**.   
   
.. image:: /static/training/t08/input.png
   :align: center

5. Back at the **Load a Custom Land Cover dataset** window you have options for selecting the band number in which the productivity data is stored, in case your input file is a multi band raster. You also have the option of modifying the resolution of the file. We recommend leaving those as defaults unless you have valid reasons for changing them.   

6. Define the year of reference for the data. In this case, since the land cover dataset for Uganda was developed for the **year 2000**, define it as such. Make sure you are assigning the correct year.

7. Click **Browse** at the bottom of the window to select the **Output raster file**.
   
.. image:: /static/training/t08/custom_landcover_menu2.png
   :align: center

8. Click on the **Edit definition** button, this will open the **Setup aggregation of land cover data menu**. Here you need to assign each of the original input values of your dataset to one of the 7 UNCCD recommended land cover classes. 

.. image:: /static/training/t08/definition1.png
   :align: center

For this example, the Uganda dataset has 18 land cover classes:
   
.. image:: /static/training/t08/uganda_legend.png
   :align: center

From the Metadata of the land cover dataset, we know that the best aggregation approach is the following:   
 - No data = 0
 - Tree covered = 1 through 7
 - Grassland = 8 through 11
 - Cropland = 12 through 14
 - Wetland = 15
 - Water body = 16
 - Artificial = 17
 - Other land = 18

9. Use the **Setup aggregation of land cover data menu** to assign to each number in the **Input class** its corresponding **Output class**.

 When you are done editing, click **Save definition file**. This option will save you time next time you run the tool, by simply loading the definition file you previously saved.

 Click **Save** to continue 
 
.. image:: /static/training/t08/definition2.png
   :align: center

7. Back at the **Load a Custom Land Cover dataset** window, click **Browse** at the bottom of the window to select the **Output raster file**.   
   
.. image:: /static/training/t08/custom_landcover_menu2.png
   :align: center   

8. Navigate to the folder where you want to save the file. Assign it a name and click **Save**.   
   
.. image:: /static/training/t08/output.png
   :align: center

9. Back at the **Load a Custom Land Cover dataset** click **OK** for the tool to run. 
   
.. image:: /static/training/t08/custom_landcover_menu3.png
   :align: center

10. A progress bar will appear showing the percentage of the task completed.      
   
.. image:: /static/training/t08/running.png
   :align: center

11. When the processing is completed, the imported land cover dataset will be loaded to QGIS.   
   
.. image:: /static/training/t08/lc_loaded.png
   :align: center

.. note:: You have one imported custom land cover data for one year (2000), but two are needed to perform the land cover change analysis. Repeat now steps 1 through 11, but this time with the most recent land cover map. For this tutorial, we will use another land cover map from Uganda from the year 2015. **Make sure to change the year date in the import menu**.

12. Once you have imported the land cover maps for years 2000 and 2015, you should have them both loaded to QGIS.

.. image:: /static/training/t08/both_lc_loaded.png
   :align: center

13. Now that both land cover datasets have been imported into Trends.Earth, the land cover change analysis tool needs to be run. Search for the Trends.Earth toolbar within QGIS, and click on the Calculate icon (|iconCalculator|).
   
.. image:: /static/common/ldmt_toolbar_highlight_calculate.png
   :align: center   

14. The **Calculate Indicators** menu will open. In that window, click on **Land cover** button found under Step 1 - Option 2.   
   
.. image:: /static/training/t08/call_lc_change_tool.png
   :align: center 

15. The **Calculate Land Cover Change** window will open. In the **Setup** tab, click on **Custom land cover dataset**. Use the drop down option next to **Initial layer (initial year)** and **Final layer (target year)** to change the dates accordingly. When done, click **Next**.
   
.. image:: /static/training/t08/lc_change_tool.png
   :align: center 

16. The **Define Degradation** tab is where you define the meaning of each land cover transition in terms of degradation. Transitions indicated in red (minus sign) will be identified as degradation in the final output, transitions in beige (zero) will be identified as stable, and transitions in green (plus sign) will be identified as improvements. 

 For example, by default it is considered that a pixel that changed from **Grassland** to **Tree-covered** will be considered as improved. However, if in your study area woody plant encroachment is a degradation process, that transition should be changed for that particular study area to degradation (minus sign).

 If you have made no changes to the default matrix, simply click **Next**.

 If you did change the meaning of some of the transitions, click on **Save table to file...** to save the definition for later use. Then click **Next**.   
   
.. image:: /static/training/t08/lc_degradation_matrix.png
   :align: center 
   
17. In the **Area** tab define the area of analysis. There are two options:

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
   
.. image:: /static/training/t08/area_uganda.png
   :align: center 

18. In the **Options** tab you can define the **Task name** and make some **Notes** to identify the analysis you are running. What information to indicate is optional, but we suggest noting:

 - Area of analysis
 - Dates
 - Indicators run   
   
.. image:: /static/training/t08/option_uganda_lc_degradation.png
   :align: center    

19. When you click **Calculate**, the **Coose a name for the output file** will open. Select where to save the file and its name, and click **Save**.  
   
.. image:: /static/training/t08/output_lc_degradation.png
   :align: center    

20. A progress bar will appear showing the percentage of the task completed.     
   
.. image:: /static/training/t08/running_lc_degradation.png
   :align: center    

21. When the processing is completed, the imported land cover degradation sub-indicator dataset will be loaded to QGIS.   
   
.. image:: /static/training/t08/loaded_lc_degradation.png
   :align: center  
   
.. note::
    Refer to the :ref:`tut_compute_sdg` tutorial for instructions on how to use the land cover sub-indicator to compute the final SDG 15.3.1 after integration with changes land productivity and soil organic carbon. 
