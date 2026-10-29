(tut_sdg_high)=
# High-resolution SDG 15.3.1 (30m, SIDS)

<!--
Draft for task B4 (issue #1081). Screenshots go in
docs/resources/en/training/t14/ (files 20-34). Each "SCREENSHOT" comment below names the file
to add; replace the comment with the image directive once the file exists:

```{image} ../../../resources/en/training/t14/<file>.png
:align: center
```

Source of the steps: LDMP/calculate_ldn.py (DlgCalculateOneStep, presets,
FWv2 coverage message), the .ui files, and the GEE scripts in
gee/sdg-15-3-1-indicator and gee/sdg-15-3-1-sub-indicators. Every "TODO" must
be checked on the release candidate before the text is final.
-->

- **Objective**: Learn how to calculate the **SDG 15.3.1 Indicator** at 30 m spatial resolution for Small Island Developing States (SIDS), using the FAO-WOCAT v2 (FWv2) land productivity dynamics dataset together with the default land cover (ESA CCI) and soil organic carbon (SoilGrids) data. In this tutorial we will use The Bahamas as an example, but you can choose any of the 40 SIDS covered by the dataset. <!-- TODO: confirm The Bahamas is in the FWv2 coverage list (Zenodo 15276520) -->

- **Estimated time of completion**: To be confirmed <!-- TODO: time a full run -->

- **Internet access**: Required

:::{note}
The FAO-WOCAT v2 land productivity dynamics dataset is only available for 40 Small Island Developing States. See more details on the [Zenodo record](https://zenodo.org/records/15276520). If your region of interest is outside these countries, use the {ref}`tut_land_degradation` tutorial instead.
:::

## Calculate the sub-indicators at 30 m

1. Click on the Trends.Earth toolbar within QGIS, and click on the **Trends.Earth** icon.

   ```{image} ../../../resources/en/common/icon-trends_earth_selection.png
   :align: center
   ```

2. The **Trends.Earth** panel will open. In the **Algorithm** window, click on **SDG 15.3.1 - Land degradation** and select **Execute remotely** under **Sub-indicators for SDG 15.3.1**.

   ```{image} ../../../resources/en/training/t14/20_algorithm_panel_sub_indicators.png
   :align: center
   ```

3. The region of interest is already set up in Settings. If you need to change, select the **Change region** button. Make sure the region is one of the SIDS covered by the dataset.

   :::{note}
   Refer to the {ref}`tut_settings` section of this manual for more information on setting up your area of interest.
   :::

4. In the **SDG15.3.1 Indicator (one-step) | Land Degradation** dialog, under **Land productivity data**, select **FAO-WOCAT v2 land productivity dynamics (30m, SIDS only)**.

   ```{image} ../../../resources/en/training/t14/21_fwv2_option.png
   :align: center
   ```

5. Select the dataset for the **Baseline period** from the **Land Productivity Dynamics (LPD) dataset** drop-down list (**Land Productivity Dynamics FWv2 (2000-2015)**). Select the **Include reporting period (for comparison to baseline)** check box and choose the dataset for the reporting period: **Land Productivity Dynamics FWv2 (2004-2019)** or **Land Productivity Dynamics FWv2 (2008-2023)**. If you want to add yet another reporting period, click on **Add reporting period**.

   The initial and final years are filled in from the dataset you choose.

   ```{image} ../../../resources/en/training/t14/22_fwv2_periods.png
   :align: center
   ```

   :::{note}
   If you are preparing data for reporting to the UNCCD, you can instead select the preset **UNCCD Reporting (2026 reporting cycle, FAO-WOCAT v2, 30m, SIDS only)** under **Presets** and click on **Apply Preset**. It sets the baseline (2000-2015) and the two reporting periods (2015-2019 and 2015-2023).
   :::

   <!-- SCREENSHOT 23_fwv2_preset.png: Presets drop-down with the 30m SIDS preset -->

6. Type in the **Execution name** and notes.

7. Click on the **Schedule remote execution** button.

8. A message titled **Note: FWv2 dataset coverage** will remind you that the dataset is only available for 40 SIDS. Click **OK** to continue.

   ```{image} ../../../resources/en/training/t14/24_fwv2_coverage_message.png
   :align: center
   ```

9. A light blue bar will temporarily show, indicating that the task was successfully submitted. The analysis will be run in Google servers and the results are produced at the native 30 m resolution of the FWv2 data. One task is submitted for each period. <!-- TODO: add typical run time -->

10. In the **Trends.Earth** panel, select the **Datasets** window. The tasks submitted will appear in the menu with the status **RUNNING** if the **Download remotely-generated datasets automatically** is checked in **Advanced settings**. Click on the Refresh button if the analysis does not appear in the menu.

    ```{image} ../../../resources/en/training/t14/25_fwv2_datasets_running.png
    :align: center
    ```

    :::{note}
    Refer to the {ref}`tut_settings` section of this manual to learn more about **Advanced settings**.
    :::

11. Once the tasks are done, their status changes to **DOWNLOADED**. To look at the sub-indicators, select the add layer drop-down button to **Add default layers from this dataset to map**. Do this for the baseline and for each reporting period. <!-- TODO: confirm which layers are added for a FWv2 run -->

    ```{image} ../../../resources/en/training/t14/26_fwv2_add_default_layers_subindicators.png
    :align: center
    ```

## Calculate the SDG 15.3.1 Indicator

1. In the **Algorithm** window, click on **SDG 15.3.1 - Land degradation** and select **Execute locally** under **Indicator for SDG 15.3.1**.

   ```{image} ../../../resources/en/training/t14/27_algorithm_panel_indicator_local.png
   :align: center
   ```

2. In the **SDG 15.3.1 Indicator (Summary) | Land Degradation** dialog, under **Land productivity data**, select **FAO-WOCAT v2 land productivity dynamics (30m, SIDS only)**.

   ```{image} ../../../resources/en/training/t14/28_fwv2_summary_dialog.png
   :align: center
   ```

3. In the **Baseline dataset** drop-down list, select the sub-indicators dataset you calculated for the baseline period. The **Advanced (baseline)** section is already expanded: check that the **Land Productivity Dynamics (LPD) dataset**, **Land cover (degradation)** and **Soil carbon (degradation)** layers come from the same dataset.

   The **Population** check box is selected by default, so the proportion of population exposed to land degradation, disaggregated by sex, is calculated too. Check that the female and male population layers are filled in.

   :::{note}
   Make sure to carefully verify that the available layers are correctly pre-filled to the corresponding fields.
   :::

4. Select the **Include reporting period(s) for comparison to baseline** check box and, in **Progress dataset #1**, select the sub-indicators dataset you calculated for the reporting period. Check the layers in its **Advanced (reporting period) #1** section in the same way.

   ```{image} ../../../resources/en/training/t14/29_fwv2_progress_dataset.png
   :align: center
   ```

5. Select the **Execute locally** button. A progress bar at the top of the map shows the progress of the analysis.

   ```{image} ../../../resources/en/training/t14/30_fwv2_processing.png
   :align: center
   ```

6. In the **Datasets** window, the result appears as a **LOCAL** dataset named **sdg-15-3-1-summary**. Select the add layer drop-down button to **Add default layers from this dataset to map**.

   ```{image} ../../../resources/en/training/t14/31_fwv2_summary_add_layers.png
   :align: center
   ```

7. The SDG 15.3.1 data will be added to the map for the region of interest.

   ```{image} ../../../resources/en/training/t14/32_fwv2_result_map.png
   :align: center
   ```

8. To see the charts and maps generated for the report, select the report drop-down button of the **sdg-15-3-1-summary** dataset and click on **Open report directory**.

   ```{image} ../../../resources/en/training/t14/33_open_report_directory.png
   :align: center
   ```

9. The report directory will open. It contains the charts of the analysis (land cover in the initial and final year, land cover change, soil organic carbon change and the SDG 15.3.1 summary area), the map figures of the indicator, and a QGIS project with the results.

   ```{image} ../../../resources/en/training/t14/34_report_directory_charts.png
   :align: center
   ```

## Troubleshooting

- **The 30m option gives no result or an empty map**: your region of interest is probably outside the 40 SIDS covered. Check the coverage on the Zenodo record above. <!-- TODO: reproduce and record the actual behaviour and error message -->

:::{note}
Refer to the {ref}`background_landdegradation` background for interpreting the results of this analysis.
:::
