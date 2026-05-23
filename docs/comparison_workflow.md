# Comparison

This page provides a space to compare the binding and perturbation datasets to
each other. Additionally, this tab introduces the option for different
variations of the same dataset. Currently that includes the alternate promoter
sets for the sequencing based binding datasets (callingcards, Mahendrawada 2025
ChEC-seq, and Rossi 2021 ChIP-exo). Additionally, for Mahendrawada 2025 and
Rossi 2021 ChIP-exo, the author's original scores are used to score the same
promoter sets, and and a view of those scores vs different promoter sets
compared to the overall promoter region score is provided (both of the original
authors called peaks rather than summing the signal over the entire promoter
region).

## Structure

The sidebar provides options to select among the binding and perturbation
datasets selected in the dataset selection tab. It also provides options to
select among promoter sets. Th user can set the "Top N" promoters over which the
responsive rate (how many of the top N promoters ranked by binding have a 
significant response in the perturbation). They can set the repsonsiveness
threshold which is controlled by the minimum effect and maximum pvalue so a
significant target in the response must have an effect size above the minimum
effect and a p-value below the maximum p-value. 

There are two tabs, the "distribution" tab and the "table" tab.
The distribution tab shows a boxplot where each point that makes 
up the distribution is a sample (probably analogous to a 
single regulator, though that is dependent on how the user has set
the filters in the select dataset page). If more than one promoter 
option is selected, then the sequencing based datasets will have 
multiple distributions. The table shows the median responsiveness 
for each dataset pair for each of the promoter options selected.

## first load

The page loads with the default settings (all selected datasets, all available
promoters, min absolute effect of 0 and max pvalue of 0.05) and the execute
analysis button is full color indicating that it needs to be clicked to populate
the visualizations. Once the user clicks execute analysis, a message appears on
the workspace that says "Running analysis, please wait. This typically takes
less than 5 seconds. Thank you for your patience." and that message persists
until the visualizations are updated with the results of the analysis.

## usage

The user interacts with the sidebar to change settings. If settings are changed,
the "Execute Analysis" button becomes full color, indicating that the user needs
to click it to update the visualizations. Once the user clicks "Execute
Analysis", the message appears on the workspace that says "Running analysis,
please wait. This typically takes less than 5 seconds. Thank you for your
patience." and that message persists until the visualizations are updated with
the results of the analysis. The "Execute Analysis" button becomes more
transparent again, indicating that the visualizations are up to date with the
current settings. The user can change settings and click "Execute Analysis" as
many times as they like, and each time the visualizations should update to
reflect the new settings.

## impact on other pages

None
