# Select Datasets

This describes the workflow through the select datasets page.

## Structure

There is a sidebar that displays the binding and perturbation datasets. Each dataset 
has a selection slider and a filter button. Clicking the filter button opens a modal that
allows the user to set filters on the corresponding dataset. There are two columns in the
modal, the left side is common characteristics and the right side is dataset specific characteristics. The common characteristics each have an option to set any of the 
settings on that dataset to strictly the corresponding dataset, or across all of the
datasets.  

The workspace displays a dataset intersections matrix. When a dataset is activated 
(either by toggling the selection slider or by setting filters), it is added as a column
and row to the matrix. The cells of the matrix display how many regulators and how 
many samples there are in the dataset (given any filters) in the diagonal and how many
regulators are common between two datasets in the off diagonal (upper triangular).
Clicking a diagonal cell opens a modal that gives information about whether or not
the regulators are represented by unique samples, and if not, what features in that 
dataset have multiple samples for the same regulator. Clicking an off diagonal cell
opens a modal that has an option to set that set of regulators (those in the pairwise 
intersection) as an "apply to all" filter on all selected datasets.

## first load

Clicking "dataset selection" (or any of the other navbar options) should, if it is
the first time the user has clicked off the homepage in this session, start the
vdb_init extended task. A message should appear on the workspace page that says
"Loading data, please wait. This typically takes less than 5 seconds. Thank you for your patience.".  

There is a default set of data selections and filters that the site developer has set, 
and those selections and filters should be added to the data object that tracks the user's
selections. This should be present before the first rendering of the select datasets page 
so that on first rendering, the selections and filters are already applied and the dataset
intersections matrix is populated.  

## usage

At this point, the user may click through the data filters in order to understand the 
data sets and filters. They may make changes, which accumulate until the user clicks 
the "apply" button at which point any filters that have been changed/datasets that have 
been selected/deselected, etc are applied. Note that choosing a set of regulators to set
as a common filter from the off diagonal of the datasets intersections should be 
treated similarly and queued until the user clicks applied. There should be a message 
on the main workspace page that says a the regulator filter is pending with an option
to cancel it. Only one of these common regulator filters should be pending at one time,
so if the user chooses a different pairwise common rgulator intersection, and there 
is already one selected by not applied, it should be replaced.  

## impact on other pages

The selected datasets determines what datasets, and what samples within each dataset,
are available for analysis on the binding, perturbation and comparison tabs.

