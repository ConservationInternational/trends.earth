.. _task_download:

Task status & download
======================

- **Objective**: Learn how to check the status of submitted tasks, download them and compute pyramids for faster visualization of results in QGIS.

- **Estimated time of completion**: 20 minutes

- **Internet access**: Required

.. note:: `Download this page as a PDF for offline use 
   <../pdfs/Trends.Earth_Tutorial04_Downloading_Results.pdf>`_

The results of Trends.Earth analysis are rasters in TIF format for indicators and XLSX spreadsheets for the tabular outputs. You will need to define in each case where files will be stored in your computer. We recommend you create a folder where to store the results for easy posterior access. The **Desktop** is a location usually selected because it is easy to find. 

1. To create a folder in your computer's desktop, navigate there by minimizing all the windows and programs you have open (Note: not closing, simply removing them from the display).

2. Once in the Desktop, **right click** on an empty space and a menu will display.

3. Move your mouse cursor to the **New** option at the bottom of the menu, and another menu will show to the right.

4. Navigate with your mouse cursor to **Folder** and right-click.
   
.. image:: /static/training/t04/create_folder.png
   :align: center

5. A new folder named **New Folder** will appear on your desktop with the name highlighted in blue. Type the name you want to assign it. In this example, we named it **Trends.Earth**. Then press the **Enter** key on your keyboard to save the name. 
   
.. image:: /static/training/t04/name_folder.png
   :align: center

6. Navigate again to QGIS, and click on the cloud with the arrow facing down icon (|iconCloudDownload|) from the Trends.Earth toolbar.   
   
.. image:: /static/common/ldmt_toolbar_highlight_tasks.png
   :align: center   

7. The **Download results from Earth Engine** will open. Click **Refresh List** to check the updated status of the tasks submitted in the previous section of the tutorial (:ref:`1-step_subindicators`). One of three messages will show there:

 - **RUNNING**: The task has been successfully submitted to Earth Engine and it is being processed. Wait a few minutes and click **Refresh list** again.

 - **FINISHED**: The task has been completed and it is ready to be downloaded.

 - **FAILED**: There has been some error in the parameters selected and the task could not be completed. Please run the tool again to make sure all parameters are correct.

.. image:: /static/training/t04/finished.png
   :align: center
 
8. When the task shows status **FINISHED** you can select it by clicking on it (it will be highlighted in blue), and them click on the **Download results** button.   
   
.. image:: /static/training/t04/download.png
   :align: center

10. A window will open for you to define the location (the folder you just created on the Desktop) and the name of the output file. Make the name as informative as possible so you can tell what information it contains the next time you want to use those results.
    
.. image:: /static/training/t04/name_output.png
   :align: center

11. The Download window will disappear and you will be brought back to the QGIS interface. You will see light blue progress bar indicating which percentage of the file has been downloaded. This could take from a few seconds to several minutes depending on the size of the area selected and the speed of the Internet connection available.   
   
.. image:: /static/training/t04/downloading.png
   :align: center

12. Once the download is completed, the results will be loaded in QGIS. In this example you'll see a layer for each of the SDG 15.3.1 computed: land productivity, land cover, and soil organic carbon.   
   
.. image:: /static/training/t04/loaded_results.png
   :align: center

   
**OPTIONAL: Computing Pyramids**
---------------------------------

 When the raster file is too big, due to a large study area, high spatial resolution, or a large number of bands in the file, the data could take several seconds to display. If you change the zoom or turn layers on an  off frequently, this could make the work a bit frustrating. An option to overcome this is to compute **Pyramids** to the file. This process will take from **minutes to hours** to run depending on the size of the area, so make sure to have enough time for it to process. To compute pyramids you have to:

13. Navigate with your cursor to the layer you want to compute pyramids for and right click over it. A menu will open. Navigate to **Properties** and click on it.

.. note::
	When using the **Calculate all three sub-indicators in one step** option (described in the previous tutorial :ref:`1-step_subindicators`), all the bands are stored in a single TIF file, so even though you see three layers loaded in the QGIS window, they all refer to the same file. This means that the pyramids need to be computed only once for the three sub-indicators.

.. image:: /static/training/t04/goto_layer_properties.png
   :align: center

14. The Layer Properties menu will open. From the options on the left, navigate to **Pyramids** and click on it.   
   
.. image:: /static/training/t04/layer_properties_general.png
   :align: center

15. Once on the **Pyramids** tab you will see a description about they are.

.. image:: /static/training/t04/layer_properties_pyramids_menu.png
   :align: center
   
16. To the right of the window you will see the **Resolutions** options. Selecting all of them will make displaying in QGIS the fastest, but this could take hours to compute depending on the file size and processing capabilities of the computer you are using. For the Uganda example, we can select them all, but if using a larger area or higher spatial resolution than the default 250m, we recommend you select alternating resolutions options (i.e. one resolution selected and one not selected, and so on). Resolutions are selected by clicking on them. When selected, they will turn blue.

 Make sure that the settings at the bottom are set to:

 - **Overview format**: External
 - **Resampling method**: Nearest Neighbour

16. Then click on the **Build pyramids** button. The progress bar next to it will show which percentage of the task has been completed.
   
.. image:: /static/training/t04/layer_properties_pyramids_parameters.png
   :align: center
   
17. When pyramids have been built you will notice that the icons next to the resolutions will have changed from **red crosses** to **yellow pyramids**.
   
.. image:: /static/training/t04/pyramids_icons_before_after.png
   :align: center
   
18. Click **OK** to go back to the QGIS main interface.
