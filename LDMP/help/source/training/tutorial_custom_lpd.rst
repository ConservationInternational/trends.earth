Use custom productivity data
=================================

- **Objective**: Learn to load custom land productivity data computed outside of Trends.Earth.

- **Estimated time of completion**: 15 minutes

- **Internet access**: Not required

.. note:: `Download this page as a PDF for offline use 
   <../pdfs/Trends.Earth_Tutorial05_Using_Custom_Productivity.pdf>`_

Land productivity data should be formatted following UNCCD guidelines for reporting indicating areas of declining, early signs of decline, stable but stressed, stable, or increasing primary productivity.
   
For the productivity data to be used in Trends.Earth the file need to be coded in the following way:
 - Declining = 1
 - Early signs of decline = 2
 - Stable but stressed = 3
 - Stable = 4
 - Increasing = 5
 - No data = 0 or -32768

 If your layer is not coded in such a way, please do the necessary adjustments prior to using Trends.Earth.
 
1. To load productivity data click on the (|iconfolder|) icon in the Trends.Earth toolbar.

.. image:: /static/common/ldmt_toolbar_highlight_loaddata.png
   :align: center

2. The **Load data** menu will open. Select **Productivity** from the **Import a custom input dataset** section.

.. image:: /static/training/t10/call_custom_lpd_menu.png
   :align: center

3. In the **Load a Custom Land Productivity Dataset** use the radio button to select the format of the input file (raster or vector). For this tutorial select raster, since the data distributed by the UNCCD is in raster format. Click on **Browse** to navigate to the productivity file you wish to import.

.. image:: /static/training/t10/custom_lpd_menu1.png
   :align: center

4. In the **Select input file** menu select the file and click **Open**.   
   
.. image:: /static/training/t10/custom_lpd_load_input.png
   :align: center

5. Back at the **Load a Custom Land Productivity Dataset** window you have options for selecting the band number in which the productivity data is stored, in case your input file is a multi band raster. You also have the option of modifying the resolution of the file. We recommend leaving those as defaults unless you have valid reasons for changing them.
6. Click **Browse** to select the **Output raster file** and navigate to the folder where you want to save the file. Assign it a name and click **OK**.
   
.. image:: /static/training/t10/custom_lpd_menu2.png
   :align: center

5. Back at the **Load a Custom Land Productivity Dataset** window click **OK** on the lower right corner to process the data.
   
6. If the values of the input file do not exactly match the requirements describe above, you will see a warning message. In many cases the warning is triggered by the definition of NoData, but the tool will still try to import it. For that reason, it is **extremely important** for you to explore the output layer to make sure the results are mapped as expected.

.. image:: /static/training/t10/warning.png
   :align: center

7. Once you click **OK** in the warning window, a progress bar will appear showing the percentage of the task completed.
   
.. image:: /static/training/t10/processing.png
   :align: center

8. When the processing is completed, the imported land productivity dataset will be loaded to QGIS.   
   
.. image:: /static/training/t10/lpd_output_loaded.png
   :align: center
   
.. note::
    Refer to the :ref:`tut_compute_sdg` tutorial for instructions on how to use the imported LPD to compute the final SDG 15.3.1 after integration with land cover and soil organic carbon.
