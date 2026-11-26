# ILUP planning: prioritization UX simplification plan

## Goal and scope

Make it possible to understand and review a ranking without knowing the
implementation or reopening every scoring profile. Simplify the existing
planning panel and dialogs; retain separate saved rankings, candidate selections,
and scenario results. This is a design and implementation plan, not an implemented
interface change.

Keep the current scoring and selection methods. Do not introduce automatic
criteria, change ARR classification, imply cross-class score comparability,
or turn ranking into budget optimization.

## 1. Establish one mental model throughout the panel

Use the same short explanation in the panel, ranking dialog, and candidate dialog:

> **ARR determines where each response applies. Criteria determine which
> locations have higher priority within that response. Candidate selection
> chooses locations from those rankings. A scenario applies your effectiveness
> assumptions to the selected targets.**

Show this compact sequence above the planning sections:

```text
ARR eligibility -> Priority scores -> Candidate areas -> Scenario targets
Which response?    Which locations?   How much / where?   Assumed outcomes?
```

Retain the option to skip ranking and candidate selection when using drawn or
imported intervention polygons. Do not present every stage as mandatory.

Explain three distinct concepts where they are used:

- **Priority score:** a relative preference from 0 to 1, not a probability of
  intervention success or a percentile.
- **Criterion importance:** a criterion's relative share of the score within
  one ARR class, not a share of selected area or funding.
- **Expected effectiveness:** a scenario assumption about intervention success,
  separate from both priority and importance.

Use the existing ARR labels with short descriptions: Avoid (protect non-degraded
land), Reduce (manage at-risk non-degraded land), Reverse (restore degraded land).
Link to classification details rather than implying that criteria establish risk.

## 2. Replace the mixed-class table with class-specific groups

Organize the ranking dialog into Avoid, Reduce, and Reverse groups. Each group
has its own criteria list and an **Add criterion to [class]...** action.
Adding a criterion uses that class explicitly rather than silently defaulting
to Avoid. Moving an existing criterion to another class is an explicit row action.

Show all three class headers, including empty classes. A class with no active,
positive-weight criteria says:

> No ranking for this class. Add a criterion if you want to select candidate
> areas for this response.

Use a short ARR context block above the groups:

```text
Eligibility map: [full ARR dataset name]
Criteria rank locations within this map; they do not change ARR classes.
[View ARR map] [Change project inputs...]
```

Keep optional land-type and jurisdiction breakdowns out of this block. Describe
them separately as reporting groups, not additional ranking criteria.

### A readable criterion row

Replace `Input | Profile | Class | Weight | Influence` with:

```text
Use | Criterion and scoring rule | Relative importance | Actions
```

The criterion cell contains a meaningful name and a second line summarizing
the scoring rule. For example, using hypothetical data:

```text
Travel distance
Road distance / band 1; nearer is preferred; 0 km = 1, 20 km = 0

Land-cover preference
Land cover / band 1; category-specific scores; 2 categories unscored
```

Use wrapping and adequate column width rather than routinely truncating names.
Show complete source names in expandable details and tooltips. Do not depend on
tooltips alone to explain scoring.

Provide visible **Edit scoring...**, **Details...**, and **Remove** actions;
double-click may also open details. Details show the full input, band or field,
scoring rule, saved profile name/revision, provenance, and data status.

Add a generated sentence in the details:

> Within Reverse locations, this criterion gives higher priority to shorter
> road distances and contributes 40% of the combined score.

The same dataset may legitimately appear in several classes, or with several
bands/profiles. Explain that these are separate uses, not extra ARR layers.
Warn about an identical active criterion added twice within the same class,
because it can unintentionally increase that preference's combined importance;
do not silently merge existing entries.

## 3. Make weight and influence one understandable concept

Keep one editable numeric control, labeled **Relative importance**, and display
its calculated **Share of class score: X%** beneath it. Remove the standalone
Influence column. Do not add independently editable weights and percentages or
require users to manually make percentages total 100.

Offer **Equal importance** as a convenience for a class, with custom relative
values available immediately. Applying equal importance is an explicit action,
not an automatic change to restored settings. New criteria can retain the
existing initial weight of 1.

Place this explanation next to the controls:

> Relative values are converted to shares within this class. Values of 2 and 1
> give shares of about 67% and 33%. Only ratios matter.

For the supplied screenshot, explain the apparent contradiction directly:

> The Reduce criterion has weight 0.500 and the Avoid criterion has weight
> 0.200. Each is the only active criterion in its class, so each contributes
> 100% of that class's score. These weights do not compare Reduce with Avoid.

For a class with one positive-weight criterion, show **Only active criterion:
100% of this class's score**. Changing its positive weight alone cannot change
that ranking. A larger weight does not necessarily produce a higher score:
it gives that criterion's preference more say.

Distinguish these states visibly:

- Unchecked: **Not used**; retained for later, omitted from scoring.
- Checked with zero weight: **No score contribution**; missing values in this
  criterion do not prevent scoring, although its input still requires validation.
- No positive weights in a configured class: an actionable validation error;
  do not display a plausible ranking or silently reset weights.

## 4. Turn adding/editing criteria into one coherent interaction

Replace the sequence of dataset and profile chooser popups with a single
**Add criterion to [class]** dialog:

1. **Choose data:** select an imported input or import a new dataset in place.
2. **Define the preference:** choose a saved scoring rule or create one.
3. **Review:** show its plain-language summary and relative importance.

Keep dataset import and reusable profile storage underneath. In ordinary UI
copy call a profile a **Saved scoring rule**, with its revision in details.

For continuous data, ask **Which values should receive higher priority?**
and label endpoints with their resulting scores and units. Show the current
clamping behavior explicitly. Preserve the observed-range helper, but explain
that an observed range is not automatically the right planning preference.

For categories, show category labels where available, stored codes, and scores.
Distinguish **Score 0: lowest priority** from **Unscored: prevents scoring where
this positive-weight criterion is required**. Do not assign category preferences
by default.

Offer explicit **Use a different saved rule** and **Save as new revision**
actions when editing. Changes apply to the current ranking draft only; other
rankings keep their stored snapshots. Never silently update all users of a
reusable profile.

Move resampling, direct-file criteria, provenance, and settings import/export
into clearly labeled advanced/details areas. Keep exclusions separate from
reporting breakdowns: exclusions change selectable land; breakdowns summarize
results without changing scores.

## 5. Make the ranking result and candidate handoff explicit

Before execution, show a small per-class summary:

> Reverse: 3 active criteria. Scores combine their preferences within Reverse.
> Locations missing any positive-weight criterion will remain unscored.

Do not present exact coverage before calculation unless it has actually been
computed. After calculation, expose the existing coverage/report information:

- ARR area, area eligible after exclusions, scored area, and coverage.
- Unscored area and exclusion information, with a clear coverage denominator.
- **View priority map** and **View scoring coverage** for each class.
- A legend distinguishing low scores, missing required data, exclusions, and
  locations outside the ARR class. Where the existing coverage data cannot
  separate causes, use a truthful combined label or report detail.

Show a prominent **Select candidate areas from this ranking...** action.
Select the completed ranking explicitly and identify its source ARR. Do not
silently substitute a different saved ranking.

In candidate selection, use the same class groups and scoring summaries.
Disable selection for a verified class with no scored pixels and explain why.
For legacy results with unavailable coverage metadata, show **Coverage unknown**
and a review/rerun action rather than treating unknown coverage as zero.

Present the existing methods in planning language:

- **Choose highest-priority locations up to an area limit** (km2).
- **Choose all scored locations meeting a minimum priority score** (0-1).

Neither method should be preselected on behalf of the planner as a new policy.
Label area previews as sampled estimates, invalidate them when settings change,
and show actual selected areas after execution. Explain that ties are
deterministic and whole pixels can leave part of an area allowance unused.
Area caps apply per class, not as a shared budget; a threshold of 0.8 does not
mean the top 20% or an 80% success rate.

After selection, show:

> These are proposed intervention locations, not scenario targets yet.
> Review the map, then add them to a scenario and set expected effectiveness.

Provide **Review candidate map** and **Configure scenario targets...** actions.
The latter opens the existing explicit target/effectiveness configuration flow.
Neither generating nor selecting candidates should automatically replace targets.

## 6. Explain changes and downstream dependencies

Keep immutable saved results and existing lineage checks. Add specific messages
instead of only generic "Needs update" states:

- ARR changed: **This ranking uses a different eligibility map. Revise ranking.**
- Ranking changed: **These candidates use an earlier ranking. Revise selection.**
- Candidates changed: **Scenario targets need review and reconfiguration.**
- Draft criteria changed: **Unsaved ranking changes; saved candidates still use
  the previous ranking. Create a new ranking to apply these changes.**

Do not invalidate saved artifacts merely because a draft is edited. Preserve
previous results, disabled criteria, profile snapshots, and selection settings.
Retain existing checks on input availability, region, file changes, and target
compatibility.

## 7. Implementation sequence

### Phase 1: clarity and reviewability

In [the ranking dialog](../LDMP/calculate_ldn_priority.py), introduce class groups,
row scoring summaries, class-aware addition, relative-importance/share copy,
row details/edit actions, and clear empty/disabled states.

Reuse [profile and input helpers](../LDMP/ldn_planning_assets.py) to generate
summaries from actual stored settings, including legacy direct-file entries.
Leave persisted criterion fields and algorithm parameters unchanged.

### Phase 2: coherent criterion setup

Consolidate dataset/rule selection, improve endpoint and category explanations,
and support explicit profile revisions without changing saved snapshots.
Preserve cancellation behavior and existing advanced-file/import/export paths.

### Phase 3: connected planning workflow

Update [the planning panel](../LDMP/ldn_planning_panel.py) and the candidate
dialog with source context, coverage explanations, explicit handoff actions,
and dependency messages. Reuse existing selection and target-configuration
actions rather than creating a parallel workflow.

Update the [tutorial](source/for_users/training/ldnplanning.rst),
[feature guide](source/for_users/features/ldnplanning.rst), and
[process diagrams](source/for_users/features/ldnplanning-process.md) alongside
the corresponding implementation phases. Keep translated strings, keyboard
navigation, accessible control labels, and smaller-window layouts supported.

## 8. Acceptance and validation

Add focused regressions to the existing
[prioritization tests](../test/test_ldn_prioritization.py) and
[planning integration tests](../test/test_ldn_planning_integration.py):

- Weights 2 and 1 in one class display approximately 67% and 33%; weights in
  different classes do not affect those shares. One criterion shows 100%.
- Disable, zero-weight, move-class, and empty-class states agree with actual
  scoring; restored drafts retain their original settings and outputs.
- Continuous and categorical summaries match stored rules, including lower
  preference, clamping, unscored categories, and advanced-file entries.
- Explicit rule revisions update only the draft entry being edited.
- Ranking-to-selection actions use the intended saved result; candidate-to-
  scenario actions require explicit effectiveness configuration.
- Changed inputs and results produce the correct review actions without
  silently replacing earlier results or targets.

Run targeted tests under the existing supported QGIS Docker environments
when implementing. This plan alone does not require a test run.

Validate a prototype with at least five representative planners before finalizing
the layout. Target at least four of five completing each task without coaching:

1. Explain why the screenshot's two unequal weights both show 100%.
2. Identify the ARR class, data preference, and importance of an existing row
   without opening its profile editor.
3. Add the same input to a second class with a different scoring rule.
4. Select the best Reverse locations up to a chosen area cap and identify
   which land cannot be selected because it is unscored.
5. Explain why candidate area and expected successful intervention area differ.

Treat failure on any task as evidence to revise the prototype, not as a need
for more tutorial text.
