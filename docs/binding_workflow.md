# Binding

This describes the workflow through the binding page. The binding page provides focused
analysis of the selected binding sets. Note that the user must have first selected 
datasets on the select datasets page (there are defaults set by the site developer)
in order to have data to analyze on the binding page. The binding data available for 
analysis should be only the data that is selected on the select datasets page, including 
the filters.

## Structure

The sidebar lets the user select among the active binding datasets (those selected on
the select datasets page) which ones to include in the analysis, via a checkbox group.
The sidebar also lets the user select which score to use (effect or p-value) and which
correlation method to use (Pearson or Spearman). The default score is effect and the
default correlation method is Pearson. There is an "Execute Analysis" button that kicks
off an extended_task to compute correlations; visualizations are absent until the first
click.

The workspace shows a brief status message while the task is computing and again while
the plots are being built after the task completes, so the workspace is never silently
blank.

The workspace displays two views on separate tabs: Distributions and Scatter.

The Distributions tab shows one box plot per dataset pair (not all pairs combined in a
single figure). Each plot contains jittered points where each point represents the
per-regulator correlation for a shared regulator across the two datasets. Selecting a
point highlights that regulator across all per-pair box plots simultaneously; the
highlight trace is updated in-place via a FigureWidget, so box plots never fully
re-render when the selected regulator changes.

The Scatter tab shows one scatter plot per active pair, keyed by the selected regulator.
Each scatter plot shows per-target binding scores for the selected regulator on both
axes, with the target gene symbol in the hover tooltip. There is also a dropdown of
regulators present in at least one active pair. The Scatter tab shows a status message
while plots are being prepared.

## first load

The sidebar defaults to effect and Pearson, with all active binding datasets checked.
Visualizations are absent until the user clicks Execute Analysis. Once clicked, a status
message appears immediately and persists through both the computation phase and the
subsequent plot-building phase. The message covers the full wait from click to final
plot appearance.

## usage

At this point, the user should be able to either select a regulator form the
drop down to highlight it in the distributions, or click on a point in the
distribution to select the regulator corresponding to that point and highlight
it across the distributions and in the scatter plot. The user should be able to
change the sidebar options and click "execute analysis" to update the
visualizations with the new options. The user should be able to change the
selected datasets on the select datasets page, and then come back to the binding
page and click "execute analysis" to update the visualizations with the new
selected datasets and filters. Note that if the user changes the selected
datasets, then the previously selected regulator may not be present in the new
set of selected datasets. If that occurs, then just select the alphabetically
first regulator in the dropdown that is present.

## impact on other pages

None
