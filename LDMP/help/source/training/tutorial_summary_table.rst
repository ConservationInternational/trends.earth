.. _tut_interpret_table:

Interpreting summary table
==========================

- **Objective**: Learn how to open and interpret the summary tables produced by Trends.Earth when computing the final SDG 15.3.1 layer.

- **Estimated time of completion**: 25 minutes

- **Internet access**: Not required

.. note:: `Download this page as a PDF for offline use 
   <../pdfs/Trends.Earth_Tutorial08_The_Summary_Table.pdf>`_

.. note::
    You will need to have previously computed SDG 15.3.1 using the **Calculate final SDG 15.3.1 spatial layer and summary table for total boundary** tool. Refer to the section :ref:`tut_compute_sdg` for instructions on how to run the analysis.

1. When you computed SDG 15.3.1 an Excel file was created with the summary table. Browse to that folder and double click on the file to open it.

.. image:: /static/training/t06/sdg_find_table.png
   :align: center

If you are using Microsoft Excel, you may see the following error messages pop-up. Click **Yes** on the first one and *OK** on the second one. We are currently working trying to identify where the error comes from, but the file is fully functional.

If you are using LibreOffice or OpenOffice, the file will load with no errors.   
   
.. image:: /static/training/t06/sdg_table_error1.png
   :align: center

.. image:: /static/training/t06/sdg_table_error2.png
   :align: center

2. The summary table file contains 5 tabs, which you can explore by clicking on each of the different names the bottom of the screen: SDG 15.3.1, Productivity, Soil organic carbon, Land Cover and UNCCD Reporting.   

3. In the **SDG 15.3.1** tab you will find the area calculations derived from the indicator map you explored in QGIS.

 For the area you run the analysis, you will see the total land area (excluding water bodies): land that experienced improvement, which remained stable, areas degraded, and also information on the areas with no data for the period selected. No data in the SDG 15.3.1 is an indication of no data in some of the input datasets used in the analysis.

.. image:: /static/training/t06/table_sdg.png
   :align: center

3. In the **Productivity** tab you will find at the top, a similar summary as previously explained, but in this case representing the results of the land productivity sub-indicator alone.

 In the sections below you will find two tables, each containing area information (in sq. km) for each of the land cover transitions found in the study are during the period analyzed broken by each of the 5 final land productivity classes: Increasing, Stable, Stable but stressed, Early signs of decline, and Declining.
   
.. image:: /static/training/t06/table_productivity.png
   :align: center

4. In the **Soil organic carbon** tab you will find at the top, a similar summary as previously explained, but in this case representing the results of the soil organic carbon sub-indicator alone.   

 In the sections below you will find two tables:
 
 - The first one contains information on changes in carbon stocks from the baseline (initial year of analysis) to the target (final year of analysis).
 - The second presents information soil organic carbon change from baseline to target by type of land cover transition (as percentage of initial stock).

.. image:: /static/training/t06/table_soc.png
   :align: center
   
5. In the **Land cover** tab you will find at the top, a similar summary as previously explained, but in this case representing the results of the land cover change sub-indicator alone.      
   
 In the sections below you will find two tables:
 
 - The first contains information on land cover change by cover class (sq, km and %).
 - The second contains information on land area by type of land cover transition (sq. km).
   
.. image:: /static/training/t06/table_landcover.png
   :align: center

6. In the **UNCCD Reporting** tab you will find five tables containing similar information as the one presented in the previous tabs, but in this case specifically formatted to match the reporting template required by the UNCCD. Each table indicates at the top the page number and section of the template the information is referring to.
   
.. image:: /static/training/t06/table_unccd.png
   :align: center
