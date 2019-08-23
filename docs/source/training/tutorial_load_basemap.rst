.. _tut_load_data:

Load results and basemap
========================

- **Objective**: Learn how to load into QGIS results from previous analysis run on Trends.Earth, and how to load a base map to make help with the interpretation of spatial patterns displayed by the indicators.

- **Estimated time of completion**: 15 minutes

- **Internet access**: Required only the first time you load a base map, since the information needs to be downloaded. Once the data is stored in your computer base maps can be loaded without Internet access.

.. note:: `Download this page as a PDF for offline use 
   <../pdfs/Trends.Earth_Tutorial09_Loading_a_Basemap.pdf>`_

1. To load results from previous Trends.Earth analysis into QGIS click on the (|iconfolder|) icon in the Trends.Earth toolbar.

.. image:: /static/common/ldmt_toolbar_highlight_loaddata.png
   :align: center

2. The **Load data** menu will open. Select **Load and existing TRENDS.EARTH output file** from the **Load a dataset produced by TRENDS.EARTH** section.   
   
.. image:: /static/training/t07/menu.png
   :align: center

3. Click the **Browse** button on the **Open a Trends.Earth file** window.
   
.. image:: /static/training/t07/input_list1.png
   :align: center   
   
3. On the **Select a Trends.Earth output file** window navigate to the folder where you stored the data and select the file to load, and click **Open**.
   
.. image:: /static/training/t07/selectinput.png
   :align: center

4. You will be back at the **Open a Trends.Earth file** window, but this time you will see many layers listed under the **Select a layer(s)** section. Each of those options is a band in the raster file you downloaded from Trends.Earth. The number of bands and specific information in each of them will vary, but in any case, this tool will show you information to allow you to decide which layers to display. 

In this case, since this layer is the result of the 1-step analysis (:ref:`tut_compute_sdg`), the file contains information for land productivity, land cover and soil organic carbon.

If you only want to see the final layer for each of the sub-indicators, simply leave the default selection and click **OK**.
   
.. image:: /static/training/t07/input_list2.png
   :align: center

5. The selected layers will be displayed on the QGIS map.   
   
.. image:: /static/training/t07/loaded_data.png
   :align: center

**Adding a basemap**
---------------------------------

Basemaps are very useful as a reference for identifying specific locations in maps. When downloaded, Trends.Earth results are displayed on an empty QGIS project, which could limit the user ability for identifying know places in the landscape. To facilitate this process, you can use the **Add Basemap** tool which will load country and state boundaries, roads, rivers, cities, coastlines and water bodies with labels to the QGIS project.

1. To load the tool click on the visualizations tool icon on the Trends.Earth toolbar.

.. image:: /static/common/ldmt_toolbar_highlight_reporting.png
   :align: center  

2. Click on **Add basemap**.   
   
.. image:: /static/training/t07/basemap.png
   :align: center

3. On the **Add basemap** window you can do one of two things:

 - **Use a mask option selected** will create a mask blocking all the information outside of the selected area. In this example, all the information outside of Uganda will not be displayed on the map. This option is useful when displaying the sub-indicators downloaded from Trends.Earth, since the data download is not clipped to administrative boundaries (a bounding box is used instead). You can use first and second level administrative boundaries.
   
 - **Use a mask option not selected** will load all the reference information, but no mask will be applied. 
   
.. image:: /static/training/t07/basemap_setup.png
   :align: center

4. The first time you run this tool after installing Trends.Earth, the information will be downloaded from the Internet, so make sure you are connected. The progress bar will indicated the percentage of the task completed. The data will remain stored in your computer for future use.
   
.. image:: /static/training/t07/basemap_downloading.png
   :align: center

5. Once the basemap is loaded, you will notice the information added to the map and to the Layer panel. The basemap has information for:

 - Lake
 - River
 - Coastline
 - City
 - Disputed border
 - Subnational border
 - National border
 - Ocean
    
.. image:: /static/training/t07/basemap_loaded.png
   :align: center
