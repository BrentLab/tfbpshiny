# Dataset selection

The Dataset selection page decides which datasets, and which samples within each
dataset, every other page analyses.

## Structure

The **sidebar** lists the binding and perturbation datasets under two headings. Each
dataset row has a switch that activates it and a filter button that opens its filter
modal. Hovering over a dataset's name shows its description. The modal has two columns: characteristics
shared across datasets on the left, each with an "Apply to all datasets" toggle that
copies the setting to every dataset with that characteristic, and dataset-specific
characteristics on the right. "Queue Filters" stages the modal's settings; "Reset"
clears them.

Experimental-condition columns with defined levels appear as checkboxes, each
labelled with the level's definition. Selecting values of another characteristic,
such as carbon source, narrows the condition checkboxes to the conditions that occur
with it. When the dataset already has filters, the modal opens with those other
characteristics set to the values that occur with the filters, and offers only the
conditions that match.

Edits are staged, not applied. While any switch or filter differs from what is applied,
the sidebar shows "Dataset selection has changed. Click Apply Changes to update." and
the **Apply Changes** button is highlighted; clicking it commits every staged change at
once. A switch whose state is staged but not yet applied is drawn yellow.

The **workspace** shows the dataset intersection matrix, with one row and one column
per active dataset:

- a diagonal cell shows the dataset's regulator and sample counts under its filters.
  Clicking it opens a modal that says whether every regulator is represented by one
  sample and, if not, which characteristics distinguish a regulator's samples;
- an off-diagonal cell (upper triangle) shows the number of regulators the two datasets
  share. Clicking it opens a modal whose "Select common regulators" button restricts
  every dataset to that shared set immediately, as a `regulator_locus_tag` filter; the
  cell stays highlighted while that restriction is in force.

Below the matrix, **Regulators by Dataset** lists each regulator against the active
datasets it appears in, with a search box to pick out regulators.

## First load

The page opens with the default selection already applied: the datasets marked
`active_default` in the collection config's tags are switched on, and
`DEFAULT_DATASET_FILTERS` (`tfbpshiny/utils/vdb_init.py`) is applied. The defaults are
chosen so that every dataset has exactly one sample per regulator.

## Export

When at least one dataset is active, the sidebar footer offers an export. The download
is not the data itself but a small kit, `tfbpshiny_export-<datetime>.tar.gz`, that the
user runs on their own machine to pull the data through `labretriever`. Extracting it
creates `tfbpshiny_export-<datetime>/` with:

- `brentlab_yeast_collection.yaml`: a copy of the collection config, so the script
  resolves the same HuggingFace repositories and configs as the app;
- `fetch_data.py`: one block per active dataset, embedding the SQL and bound parameters
  of `metadata_query` and `full_data_query` under the current filters. Run, it queries
  `labretriever.VirtualDB` for each dataset and writes one subdirectory per dataset
  containing `metadata.csv`, `annotated_features.csv` and, when a description is
  available, a `README.md`;
- `requirements.txt`: the dependencies `fetch_data.py` needs (`labretriever`);
- `README.md`: how to create a virtual environment, install the requirements and run
  the script.

## Effect on other pages

The active datasets and the applied filters determine the datasets and samples the
Binding, Perturbation, Comparison and Figures pages draw from. Filters set on a primary
dataset apply to all of its promoter-set and peak-calling variants.
