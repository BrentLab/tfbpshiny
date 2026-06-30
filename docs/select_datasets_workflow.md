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

## export datasets

When the user clicks "Export Selected Datasets" on the workspace page, the app does
**not** query the data itself and bundle the results into the tarball. Instead it builds
a small "export kit" tarball (`tfbpshiny_export.tar.gz`) that the user runs on their own
machine to pull the data via `labretriever`. This moves the cost of materializing
potentially large query results off of the shiny server and onto the user's environment.

The tarball contains, at the top level:

- `brentlab_yeast_collection.yaml` -- a copy of the VirtualDB configuration file
  (`tfbpshiny/brentlab_yeast_collection.yaml`) that the app itself uses to construct
  `vdb`. The exported script points `labretriever.VirtualDB` at this file so it resolves
  the same HuggingFace repos/configs as the running app.
- `fetch_data.py` -- a generated python script with one block per dataset that was
  active (selected and, if filtered, passing those filters) at the moment the user
  clicked export. Each block embeds the SQL statement(s) and bound parameters for that
  dataset -- the same `metadata_query`/`full_data_query` SQL the app would have run
  itself, built from the current `dataset_filters` and the active binding/perturbation
  dataset lists. At runtime the script does, per dataset:
  `VirtualDB("brentlab_yeast_collection.yaml").query(sql, **params)` for both the
  metadata query and the full-data query, then writes each result to disk.
- `requirements.txt` -- top-level dependencies required to run `fetch_data.py` (at
  minimum `labretriever`).
- `README.md` -- top-level instructions for the user: create a virtual environment with
  `venv`, install `requirements.txt` with `pip`, then run `fetch_data.py` from inside the
  extracted tarball directory.

Running `fetch_data.py` reproduces the same output layout the export previously wrote
directly into the tarball: one subdirectory per dataset (sanitized display name), each
containing `metadata.csv`, `annotated_features.csv`, and, when a description is
available, a per-dataset `README.md` describing the dataset's contents. The directory
structure the user ends up with on disk is unchanged from the current export format --
only how it gets there (querying locally via the script instead of on the server at
export time) has changed.

## impact on other pages

The selected datasets determines what datasets, and what samples within each dataset,
are available for analysis on the binding, perturbation and comparison tabs.

