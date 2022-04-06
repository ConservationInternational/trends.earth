.. _tut_metadata:

Dataset Metadata
==============================

- **Objective**: Learn how to edit and view dataset metadata.

- **Estimated time of completion**: 40 minutes

- **Internet access**: Not needed

1. Click on the Trends.Earth toolbar within QGIS, and click on the Trends.Earth icon.

.. image:: ../../../resources/en/common/icon-trends_earth_selection.png
   :align: center

2. The **Trends.Earth** menu will open. In the **Dataset** window, where exsting tasks are listed in the menu if the **Download remotely-generated datasets automatically** is checked in settings.

.. note::
    Refer to the :ref:`tut_settings` section of this manual to learn more about **Advanced settings**

- Select the Refresh button if no datasets appear in the menu.

3. Press the Edit metadata button to open a drop-down menu with available options

.. image:: ../../../resources/en/documentation/metadata/metadata_button.png
   :align: center

4. The drop-down menu allows to select any raster from the list of all available rasters of the dataset to edit or view its metadata. Once raster is selected a metadata editor dialog will show up.

.. image:: ../../../resources/en/documentation/metadata/metadata_editor.png
   :align: center

5. Fill in the necessary infromation or edit existing data in the dialog fields and press OK button to save your changes. Metadata will be saved in the QGIS QMD format, in a separate file for each raster in the datataset folder.

6. Metadata also can be viewed/edited from the Dataset details dialog via the same Metadata button, as described in the step 3 above.

.. image:: ../../../resources/en/documentation/metadata/dataset_details.png
   :align: center

7. When exporting dataset to the ZIP archive from the Dataset details dialog all existing metadata in the QMD format will be automatically converted to ISO XML format and packaged together with the layers.
