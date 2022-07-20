.. _basemap:

Adding a basemap
=================

Basemaps are very useful as a reference for identifying specific locations in maps. When downloaded, Trends.Earth results are displayed on an empty QGIS project, which could limit the user ability for identifying know places in the landscape. To facilitate this process, you can use the **Add Basemap** tool which will load country and state boundaries, roads, rivers, cities, coastlines and water bodies with labels to the QGIS project.

1. To load the tool click on the **Datasets** tab and select **Load Base Map** in the bottom right of the window.

.. image:: ../../../resources/en/documentation/calculate/datasets_load_base_map.png
   :align: center  

2. On the **Add basemap** window you can do one of two things:

 - **Use a mask option selected** will create a mask blocking all the information outside of the selected area. In this example, all the information outside of Uganda will not be displayed on the map. This option is useful when displaying the sub-indicators downloaded from Trends.Earth, since the data download is not clipped to administrative boundaries (a bounding box is used instead). You can use first and second level administrative boundaries.
   
 - **Use a mask option not selected** will load all the reference information, but no mask will be applied. 
   
.. image:: ../../../resources/en/training/t07/basemap_setup.png
   :align: center

3. Once the basemap is loaded, you will notice the information added to the map and to the Layer panel. The basemap has information for:

 - Lake
 - River
 - Coastline
 - City
 - Disputed border
 - Subnational border
 - National border
 - Ocean
    
.. image:: ../../../resources/en/training/t07/basemap_loaded.png
   :align: center


