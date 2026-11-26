.. _background_ldn_planning:

Land Degradation Neutrality Planning
====================================

Background
----------

Land Degradation Neutrality (LDN) aims to maintain or enhance the amount and
quality of land-based natural capital. Planning for LDN considers the response
hierarchy of **Avoid**, **Reduce**, and **Reverse**: protect land from
degradation, reduce ongoing degradation, and restore degraded land.

The experimental LDN Planning tools in Trends.Earth support spatial analysis
and comparison of proposed interventions. They use SDG 15.3.1 data and
user-supplied information to help identify eligible areas, examine priorities,
and estimate potential contributions to an LDN plan. The **LDN Planning** tab,
after **Datasets** and before **News**, keeps project inputs, intervention design,
scenario drafts and saved results together in Trends.Earth. Shared inputs are
chosen once; scenario design adds targets and effectiveness without repeating
those choices. Drafts and unchanged candidate-target settings persist between
sessions, while completed results remain immutable snapshots. Planning datasets
are grouped into preparing inputs, ranking intervention areas, selecting
candidate areas, and building scenarios. Compact area and coverage details
appear beside selected results; use the map to inspect spatial outputs. The
saved-scenario controls open the scenario workbook.

ARR classification, land-type definition, prioritization, candidate selection
and scenario execution are accessed from this tab. Independent hotspot and
observed-counterbalancing tools remain available under Experimental.

.. note::
   Refer to the :ref:`tut_ldn_planning` for instructions on using these tools.

.. only:: html

   The :ref:`ldn_planning_process` illustrates the main workflows and each
   tool's inputs, decisions, and outputs.

   .. toctree::
      :maxdepth: 1

      ldnplanning-process

Indicator and data needs
------------------------

The workflow starts with an existing SDG 15.3.1 indicator or status dataset for
the area of interest. The Avoid / Reduce / Reverse (ARR) classification uses
the selected status encoding and can also use productivity dynamics and a
custom risk raster. A separate assignment-reason band records the basis for
the classification. When no risk or productivity input is supplied, valid
non-degraded pixels default to Avoid. Assess local risk separately when using
this default. Where a supplied risk or productivity input is missing,
non-degraded pixels remain unclassified.

Other inputs depend on the analysis:

* Categorical rasters can define land types for like-for-like accounting.
* Prioritization inputs (natural capital, cost, feasibility, or
  community-defined layers) are imported once as managed datasets with
  recorded provenance, then reused across plans through saved scoring
  profiles. Bands, vector layers and numeric fields are discovered from the
  data. An advanced option also accepts a file directly.
* Proposed targets can come from selected candidate areas or from drawn or
  imported polygons with intervention and effectiveness attributes.
* The business-as-usual (BAU) rate and projection use the baseline band, or a
  reporting-period band when selected. Jurisdiction polygons provide an
  optional geographic breakdown.

Methods and interpretation
--------------------------

**Hotspot prioritization** ranks zones by the fraction of valid pixels
classified as degraded. **Intervention ranking** uses a weighted
combination of user-defined criteria separately within each ARR class. ARR
determines which response is eligible at each location; ranking does not
change that class. Criterion weights are relative importance values normalized
within their class, so only within-class weight ratios matter. A single
positive-weight criterion contributes 100% of that class's score. Class scores
are relative preferences, not probabilities, and should not be compared across
classes. Continuous values are normalized to a user-defined range; categorical
values use user-defined scores.
Weights are normalized within each class. Missing required criterion data
leave a pixel unscored, and scores are comparable only within the same class.
Optional exclusions and coverage layers help explain where scores apply.

**Select candidate areas** uses either a minimum priority score or a maximum
physical area for each selected class. A score threshold is not a percentile or
success probability; area limits apply independently to each class and to whole
pixels, so some of the requested area may remain unused. Candidate areas are
proposed locations, not scenario targets. Add the desired candidate areas to a
scenario draft and assign their expected effectiveness, a separate scenario
assumption, to compare projected plans.

**Scenario projection** estimates expected intervention effects using
the effectiveness assigned to targets. For overlapping targets of the same
response, the highest effectiveness applies. Effects are credited only where
the target response matches the ARR class. Reverse contributes expected gains;
Avoid and Reduce contribute expected avoided losses. These expected areas
depend on the input data and effectiveness assumptions.

Degraded classes in SDG 15.3.1 indicator and status bands are cumulative over
the period recorded in the band's metadata. The BAU rate is therefore the
degraded area of the reporting band (or the baseline band when no reporting
band is selected) divided by the number of years in that period. This rate is
extrapolated linearly from the end of the period to the target year. This
unconstrained projection can exceed the assessed area, especially over long
horizons. The national comparison is a simplified aggregate, and avoided-loss
estimates are upper bounds. Examine results within each land type when
considering like-for-like neutrality. The separate **LDN Counterbalancing**
assessment examines observed gains and losses by land type. Scenario
projections describe possible future outcomes; observed assessments use
measured status data.

**References**

* Cowie, A. L., et al. (2018). Land in balance: The scientific conceptual
  framework for Land Degradation Neutrality. *Environmental Science & Policy*,
  79, 25-35.
* UNCCD (2025). *Good Practice Guidance Addendum for SDG Indicator 15.3.1*,
  advanced unedited version.
