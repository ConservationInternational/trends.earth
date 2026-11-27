.. _tut_ldn_planning:

Land Degradation Neutrality Planning
====================================

* **Objective**: Explore intervention priorities and estimate their
  potential contribution to Land Degradation Neutrality (LDN).
* **Internet access**: Required to download administrative boundaries or
  remote datasets; local analyses run on your computer.

.. note::
   Refer to :ref:`background_ldn_planning` for the data requirements,
   methodology, and interpretation of the results.

.. only:: html

   Use the :ref:`ldn_planning_process` diagrams to see how the tools connect,
   including the polygon-only route to a scenario.

Prepare for analysis
--------------------

1. Open the **LDN Planning** tab in Trends.Earth, after **Datasets** and before
   **News**, and create a named planning project. All planning calculations run
   locally. The tab shows the
   current region with the usual **Change region** control. Its four sections
   organize work into **Prepare inputs**, **Rank intervention areas**,
   **Select candidate areas**, and **Build scenarios**. Sections can be
   collapsed independently; their expanded state and scroll position are
   remembered per project. Each revision creates a new result; inspect its
   operation-specific settings before running. Scenario targets and
   effectiveness are edited directly in this tab. The indicators distinguish
   matching recorded inputs, mismatches needing an update, and unverified
   inputs. New analyses record their area and selected Trends.Earth source
   dataset IDs; older results with missing information are marked unverified.
   Check dataset coverage separately. Scenario runs also check input and
   candidate-mask checksums. Inline result details show available areas and
   coverage; use **Map** to inspect spatial outputs.
2. Set the area of interest with **Change region**. Prepare an SDG 15.3.1
   status dataset for that region using the :ref:`land degradation tutorial
   <tut_land_degradation>`. For a scenario, also prepare a baseline indicator
   dataset and, optionally, a reporting-period indicator or status dataset
   to base the business-as-usual (BAU) rate on the reporting period.
3. Give each task a descriptive name and optional notes. Run the calculation,
   then use the panel to inspect selected outputs and open their maps. Use the
   saved-scenario controls to open a scenario workbook. The **Datasets** tab
   remains available for loading outputs and opening report folders. Keep inputs
   and the region consistent across related planning steps.

The project records the current area geometry when it is created. If the
current area changes, return to the project area or explicitly adopt the new
area in the panel. Review affected selections and update or rerun results as
needed. Project selections are stored in QGIS settings; the datasets themselves
remain in the usual Trends.Earth data directory. Priority criteria drafts are
separate for each project. Scenario drafts remember targets, effectiveness,
names and notes; shared reporting data, years and breakdowns are configured
once in the project. Working edits persist when switching tabs or reopening
QGIS.

ARR, land-type and candidate-area results submitted from the panel are selected
automatically in their originating project when they finish. Select an
intervention-priority result explicitly. A completed scenario appears as the
draft's latest result; use **Select this result** or choose it from the saved
results list. Changing a selection leaves completed results unchanged.
Use **Draft menu > Duplicate selected result as new draft...** to restore a
result's scenario settings into a new draft. Different reference inputs require
rebasing the targets or creating a project with the saved inputs.
Select a saved result and use **Compare with selected scenario...** to run the
current draft against it. Compatibility is checked before submission and again
during execution. Independent hotspot and observed-counterbalancing tools remain
under Experimental.

.. note::
   If a selection list has no layers, check the current region and complete
   the required preceding analysis. Some lists contain compatible saved
   Trends.Earth datasets for the selected region.

Classify Avoid / Reduce / Reverse
---------------------------------

1. In **Prepare inputs**, select **Classify land...**. Select an SDG 15.3.1
   indicator or status layer. Its recorded band type determines whether it
   uses the **3-class indicator** or **7-class expanded status** encoding.
2. Optionally select a Land Productivity Dynamics layer. Non-degraded pixels
   with stable but stressed productivity are assigned to Reduce.
3. Optionally choose a custom risk raster, band, and threshold. Values above
   the threshold indicate risk. Missing supplied risk or productivity data
   leave non-degraded pixels unclassified.
4. Run the task. Inspect the ARR classification with **Map** and open the
   assignment-reason band from **Datasets**. In the absence of risk and
   productivity inputs, valid non-degraded areas default to Avoid; consider
   additional local risk information when interpreting this assignment.

Explore hotspots and define land types
--------------------------------------

These analyses can be run independently of intervention ranking.

* **Degradation Hotspot Prioritization**: Select a status layer and choose
  first-level administrative units, a polygon file, or a regular fishnet
  grid. Run the task and inspect the ranked zones and report. Rank 1 has the
  highest degraded fraction. The encoding is taken from the selected band
  type. Hotspots use the status raster extent and supplied zones without an
  additional current-region mask. Prepare inputs for the area you intend to
  assess.
* **Define land types...**: Add one or more categorical rasters representing
  land potential, such as land cover and soil classes. Each unique
  combination becomes a land type. Run the task to save a reusable layer for
  the scenario breakdown or LDN counterbalancing assessment. The report in
  the dataset folder lists the area of each land type. Priority reports use
  these land type names when saved land types are selected as the project
  breakdown.

Rank intervention areas
------------------------

1. Import each prioritization dataset once using **Import LDN prioritization
   input** from the Datasets panel import menu (or **Import dataset** in the
   **Add criterion** menu). Choose the raster or polygon file; the importer shows the
   detected bands or vector layers so you can pick from what is actually in
   the file. Give the dataset a name, and optionally open **Metadata...** to
   record attribution, source and other details in the same preset editor
   used by the other import tools — nothing is required, and missing entries
   appear as "Not specified" in reports. The data are
   copied into managed Trends.Earth storage with their original values, bands
   and nodata preserved, and appear in the Datasets panel like any other
   dataset.
2. Select **Rank intervention areas...**. The project ARR classification,
   saved land-type breakdown, and jurisdictions are inherited from the project;
   use **Change in project** to return to the panel. Set breakdowns under
   **Build scenarios > Scenario inputs and projection period > Projection
   period and breakdown**. The ranking uses land-type summaries when **Saved
   land types** is selected there; the **Land cover** option applies to
   scenarios.
3. Open the **Avoid**, **Reduce**, or **Reverse** tab and select **Add
   criterion > Add imported input**. Choose a dataset, then pick one of its
   saved scoring profiles or create a new one. In the profile editor, choose
   the band or numeric field from a dropdown, then either:

   * **Continuous values**: choose whether higher or lower values receive
     higher priority and set the normalization range. **Use observed range**
     fills the range from the data, shows a compact histogram of the value
     distribution, and reports whether the statistics are sampled or exact.
     Values outside the range are clamped.
   * **Categories / classes**: select **Discover categories from data** and
     score each code in the table. Codes left unchecked remain unscored;
     assigning a score of zero includes a category at the lowest score.
     Categorical data always use nearest-neighbour alignment.

   Profiles are saved with the input as numbered revisions, so a dataset is
   configured once and reused across plans and sessions.
4. Add criteria on each response's tab. ARR determines which locations are
   eligible for each response; criteria rank locations within that class and
   never change their ARR class. Each criterion card shows its input, scoring
   rule, relative importance, and calculated share of that class's score. Only
   ratios matter: weights 2 and 1 contribute about 67% and 33%. A single
   positive-weight criterion is 100% of its class score regardless of its
   positive weight, so its weight cannot change the ranking by itself. Weights
   in different classes do not interact. Use **Set equal importance** to reset
   used criteria in a class equally; unchecked criteria are retained but not
   used. A zero-weight criterion contributes nothing and its missing data do
   not prevent scoring. Missing data in a positive-weight criterion leave that
   location unscored. Class scores are relative preferences, not success
   probabilities, and scores should not be compared across classes.
5. On **Setup**, optionally expand **Exclusions** to add an exclusion raster.
   Values greater than zero are excluded; missing exclusion values remain
   unscored. Expand **Reporting breakdowns** to choose land-type summaries or a
   jurisdiction breakdown. The configuration is kept as a draft between
   sessions; **Settings > Export settings...** saves it to a file for sharing,
   **Settings > Import settings...** loads saved settings, and **Settings >
   Advanced: add from file...** accepts a one-off dataset. Help is available
   from **Show help**.
6. Run the task, select the completed result under **Intervention priorities**,
   and examine its priority map and inline coverage. Coverage bands and
   detailed reports are available from **Datasets** and its report folder.
   The Avoid, Reduce and Reverse layers use the same light-to-dark green scale:
   low (0–0.333333), medium (>0.333333–0.666667), and high
   (>0.666667–1) relative priority. Pixels outside the class, excluded pixels,
   and pixels missing any required criterion are transparent, not low priority;
   consult the coverage bands to distinguish them. Compare scores only within
   the same class and repeat with different weights to explore sensitivity.

Select candidate areas
----------------------

1. Open **Select candidate areas** and use the project's saved
   **Intervention priorities**.
2. Enable each response class to include. For each enabled class choose either
   **Choose all scored locations meeting a minimum priority score** or
   **Choose highest-priority locations up to an area limit**; only the control
   for the chosen method is shown. A score threshold is not a percentile or
   success probability. Area caps apply independently to each class, not as a
   shared budget. **Estimate selected area** shows a sampled
   estimate of how much scored area each setting would keep (and, for
   area caps, roughly where the cap binds on the score scale); the final run
   uses the exact deterministic algorithm. Threshold selection includes scored
   pixels at or above the specified value. Area selection ranks pixels by
   score, resolves ties deterministically, and adds whole pixels that fit
   within the area limit.
3. Run the task. Inspect the candidate map and inline actual selected areas.
   To use a class as a scenario target, its selection must contain pixels;
   adjust the settings or disable an empty class and rerun the selection.
   Existing scenario targets remain unchanged until configured again. To
   revise candidates, change the criteria or selection settings and run the
   relevant steps again.

Candidate areas are proposed locations, not scenario targets or predicted
successful area. In **Build scenarios**, explicitly add the desired candidate
classes as targets and set expected effectiveness for each. Effectiveness is a
separate scenario assumption; it does not change the ranking or candidate mask.

Build a scenario and compare it with BAU
----------------------------------------

1. In **LDN Planning**, select the project's ARR and baseline indicator once.
   Optionally select a reporting-period band to base the BAU rate on that
   period. Status encodings are taken from dataset metadata.
2. In **Scenario inputs and projection period > Projection period and
   breakdown**, review the start and end years. When usable period metadata is
   available, these years are read from the bands and locked. Without a
   reporting band, they are the baseline band's period. With a reporting
   indicator band, they are that band's own period. With a reporting status
   band, they run from the baseline start to the reporting end. If the
   necessary metadata is unavailable, enter the years for the period measured
   by the selected rate band. The BAU rate is that band's degraded area divided
   by the number of years in the period, projected linearly from the end year.
   Set the projection target year. Choose saved land types, land cover, or no
   breakdown, and optional jurisdictions here. A new project starts with no
   land-type breakdown; creating land types selects the saved breakdown.
   Select first-level administrative units for the selected country or choose
   a polygon file directly from the **Jurisdictions** dropdown. To replace a
   polygon file, select its entry in the dropdown again.
3. In **Build scenarios**, choose one or both target sources:

   * Select a result in the project's **Candidate areas** section, enable
     **Include candidate areas**, and select **Set expected effectiveness...**.
     Set expected effectiveness (0–1) for each selected response class and
     choose **Add targets to scenario**. The resulting targets apply only to
     matching ARR classes and can be compared with other scenario drafts.
   * Create a layer to draw polygons in QGIS, or import a polygon file. Set
     each target's ``intervention`` to ``avoid``, ``reduce``, or ``reverse``
     and its ``effectiveness`` to a fraction from 0 to 1. For imports, map
     fields or provide defaults and explicitly select fraction or percent
     units. Use **Add polygons... > Use selected saved layer** to snapshot the
     selected layer. Save drawn edits for later use.

   Loading a layer again offers to replace its previous target snapshot.
   Loading reads live QGIS edits without committing them. If a candidate raster
   no longer matches its report, generate a new selection and set its targets
   again.
4. Candidate-target settings persist while the candidate dataset, mask
   contents, ARR and region remain unchanged. Set expected effectiveness again
   to change per-response assumptions. Each time the dialog opens, its class
   values start from the previously stored default, so review every class.
   Changing **Default expected effectiveness** in the open dialog sets the
   default for future configurations; update the class values separately for
   this configuration. **Add targets to scenario** replaces existing candidate
   targets with the displayed class values. If upstream priorities or candidate
   inputs differ, update the selection and configure its targets again.
5. Select **Run scenario** and inspect the probability layers and saved-scenario
   result card. **Export scenario report...** opens its workbook. Reverse
   contributes expected gains, while Avoid and Reduce contribute expected
   avoided losses. Compare assumptions and results by land type, along with
   the simplified national BAU comparison. A new run creates a saved result;
   use **Select this result** to select it. For a zero-intervention comparison,
   leave both target sources unchecked and continue past the no-target prompt.

For a comparison between saved scenarios, use the same area, ARR and status
inputs, encodings, time horizon, land types, and jurisdictions. Comparisons
also require recorded checksums and matching input paths, except that
single-file GeoJSON jurisdictions, including downloaded administrative
boundaries, can have different paths when their checksums match. Changed
boundaries or missing checksums prevent comparison. Explore uncertainty by
changing effectiveness, criteria, weights, or targets and running additional
scenarios.

Assess observed counterbalancing
--------------------------------

To assess observed gains and losses, open **Experimental > LDN
Counterbalancing**, select a 7-class expanded status layer and a saved layer
from **Define Land Types**, and run the assessment. Inspect results for each
land type. This assessment uses observed status data; scenario outputs
describe projected effects.
