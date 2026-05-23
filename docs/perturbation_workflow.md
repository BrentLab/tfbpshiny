# Perturbation

This describes the workflow through the perturbation page. The perturbation page
provides focused analysis of the selected perturbation sets. Note that the user must
have first selected datasets on the select datasets page (there are defaults set by
the site developer) in order to have data to analyze on the perturbation page. The
perturbation data available for analysis should be only the data that is selected on
the select datasets page, including the filters.

Perturbation datasets measure the transcriptional response to TF manipulation rather
than direct TF-DNA binding. Current datasets include TFKO experiments (Hu 2007,
Kemmeren 2014, Hughes 2006 knockout), overexpression experiments (Hughes 2006
overexpression, Hackett 2020), and auxin-inducible degron RNA-seq (Mahendrawada 2025).
Each dataset reports a per-target-gene effect column (e.g. log2FoldChange, Madj,
mean_norm_log2fc) and, where available, a p-value column.

## Structure

The sidebar lets the user select which score to use (effect or p-value) and which
correlation method to use for comparing two datasets (Pearson or Spearman). There
is no dataset multi-selector in the sidebar; the perturbation datasets analyzed are
exactly those selected on the select datasets page. The default score is effect and
the default correlation method is Pearson. There is an "Execute Analysis" button that
kicks off an extended_task to compute correlations; visualizations are absent until
the first click. Changing sidebar options does not update visualizations until Execute
is clicked again.

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

The Scatter tab shows one scatter plot per active pair, keyed by the selected
regulator. Each scatter plot has the per-target score for the selected regulator on
both axes (x = dataset A score for that regulator's samples; y = dataset B score).
The axis labels include the dataset display name and the actual column name used (e.g.
"2014 TFKO (Kemmeren): Madj"). The hover tooltip on each scatter point shows the
target gene symbol. There is also a dropdown menu of regulators present in at least
one active pair. Selecting a regulator from the dropdown highlights it in the
boxplots and updates the scatter plots. If the selected regulator is absent from a
dataset in a given pair, that pair's scatter plot is omitted and a note is displayed
listing the datasets where the regulator was not found. The Scatter tab shows a status
message while plots are being prepared after a regulator change.

## first load

The sidebar defaults to effect and Pearson. Visualizations are absent until the user
clicks Execute Analysis. Once clicked, a status message appears immediately and persists
through both the computation phase and the subsequent plot-building phase. If no
perturbation dataset pairs are active, the workspace shows an empty-state message
prompting the user to select datasets on the select datasets page.

## usage

The user can select a regulator from the dropdown or click a point in the boxplot
to set the selected regulator. Selecting a regulator highlights it across all pairwise
distributions and updates the scatter plots to show that regulator's per-target scores.
The user can change the score (effect vs. p-value) or correlation method from the
sidebar, then click Execute Analysis to recompute. The user can return to the select
datasets page, change the active perturbation datasets or their filters, then come back
and click Execute Analysis to update. If the previously selected regulator is not
present in the new result, the alphabetically first available regulator is selected
automatically.

Not all datasets expose a p-value column. When the user selects p-value and a dataset
in an active pair has no p-value column, that pair is omitted from the analysis and
a note is displayed.

## impact on other pages

None
