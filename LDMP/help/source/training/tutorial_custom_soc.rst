.. _tut_custom_soc:

Use custom soil data
==========================

- **Objective**: Learn how to load custom soil organic carbon data to compute the carbon change sub-indicator using Trends.Earth.

- **Estimated time of completion**: 20 minutes

- **Internet access**: Not required

.. note:: `Download this page as a PDF for offline use 
   <../pdfs/Trends.Earth_Tutorial06_Using_Custom_Soil_Carbon.pdf>`_

.. _load_custom_soc:

Loading custom soil organic carbon data
---------------------------------------

.. note:: This tool assumes that the units of the raster layer to be imported are **Metrics Tons of organic carbon per hectare**. If your layer is in different units, please make the necessary conversions before using it in Trends.Earth.

1. To load soil organic carbon data click on the (|iconfolder|) icon in the Trends.Earth toolbar.

.. image:: /static/common/ldmt_toolbar_highlight_loaddata.png
   :align: center

2. The **Load data** menu will open. Select **Soil organic carbon** from the **Import a custom input dataset** section.
   
.. image:: /static/training/t09/custom_soc.png
   :align: center

3. In the **Load a Custom Soil Organic Carbon (SOC) dataset** use the radio 
   button to select the format of the input file (raster or vector). For this 
   tutorial select raster, since the data distributed by the UNCCD is in raster 
   format. Click on **Browse** to navigate to the soil organic carbon file you 
   wish to import.
   
.. image:: /static/training/t09/custom_soc_menu1.png
   :align: center

4. Use the **Select input file** window to navigate to the file to be imported, select it, and click **Open**.   
   
.. image:: /static/training/t09/soc_input.png
   :align: center

5. Back at the **Load a Custom Soil Organic Carbon (SOC) dataset** window you have options for selecting the band number in which the productivity data is stored, in case your input file is a multi band raster. You also have the option of modifying the resolution of the file. We recommend leaving those as defaults unless you have valid reasons for changing them.

6. Define the year of reference for the data. In this case, we will assume the soil organic carbon data is from 2000, but if using local data, make sure you are assigning the correct year.

7. Click **Browse** at the bottom of the window to select the **Output raster file**.
   
.. image:: /static/training/t09/custom_soc_menu2.png
   :align: center

8. Navigate to the folder where you want to save the file. Assign it a name and click **Save**.
   
.. image:: /static/training/t09/soc_output.png
   :align: center

9. Back at the **Load a Custom Soil Organic Carbon (SOC) dataset** click **OK** for the tool to run.

.. image:: /static/training/t09/custom_soc_menu2.png
   :align: center

10. A progress bar will appear showing the percentage of the task completed.      
   
.. image:: /static/training/t08/running.png
   :align: center

11. When the processing is completed, the imported soil organic carbon dataset will be loaded to QGIS.
   
.. image:: /static/training/t09/soc_output_map.png
   :align: center

Calculating soil organic carbon with custom data
------------------------------------------------

Once you have imported a custom soil organic carbon dataset, it is possible to 
calculate soil organic carbon degradation from that data. To do so, first 
ensure the custom soil organic carbon data is loaded within QGIS (see 
:ref:`load_custom_soc`).

#. To calculate soil organic carbon degradation from custom data, first click 
   on the (|iconCalculator|) icon on the Trends.Earth toolbar:

.. image:: /static/common/ldmt_toolbar_highlight_calculate.png
   :align: center

#. The "Calculate indicators" menu will open. Select "Soil organic carbon" 
   from the "Option 2: Use customized data" section.
   
.. image:: /static/training/t09/custom_soc_calculate.png
   :align: center

#. The "Calculate Soil Organic Carbon" window will open. Click the radio button 
   next to "Custom land cover dataset" and select either "Import" to import a 
   custom land cover dataset, or "Load existing" to load a land cover dataset 
   you have already processed in Trends.Earth. Be sure to select both an 
   "Initial layer" and a "Final layer". See the :ref:`tut_custom_lc` tutorial 
   for more information on loading land cover datasets. Once you have selected 
   both datasets, click next:

.. image:: /static/training/t09/calc_soc_select_lc.png
   :align: center

#. On the next screen, click the check box next to "Custom initial soil organic 
   carbon dataset", and then use the "Import" or "Load existing" buttons to 
   either import custom soil carbon layer (:ref:`load_custom_soc`) or to load 
   an existing one that has already been calculated:

.. image:: /static/training/t09/calc_soc_choose_soc_data.png
   :align: center

#. Click "Next". Now, choose the area you wish to run calculations for:

.. image:: /static/training/t09/calc_soc_choose_area.png
   :align: center

#. Click "Next". on the last screen, enter a task name or any notes you might 
   wish to save (this is optional) and then click "Calculate":

.. image:: /static/training/t09/calc_soc_final_page.png
   :align: center

#. A progress bar will appear on your screen. Do not quit QGIS or turn off your 
   computer until the calculation is complete.

.. image:: /static/training/t09/calc_soc_calculating.png
   :align: center

#. Once the calculation is complete, three layers will load onto your map: 1) 
   the final soil organic carbon layer, 2) the initial soil organic carbon 
   layer, and 3) the soil organic carbon degradation layer:

.. image:: /static/training/t09/calc_soc_done.png
   :align: center

#. For example, we can see areas of degradation in soil carbon around Kampala:

.. image:: /static/training/t09/calc_soc_deg_map.png
   :align: center

.. note::
    Refer to the :ref:`tut_compute_sdg` tutorial for instructions on how to use 
    the imported soil organic carbon data to compute the final SDG 15.3.1 after 
    integration with land cover and land productivity.
