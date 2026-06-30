# Comparison

This page provides a space to compare the binding and perturbation datasets to each
other. It also introduces alternate variations of the same binding dataset: alternate
promoter sets (for callingcards, Mahendrawada 2025 ChEC-seq, and Rossi 2021 ChIP-exo),
and, for Mahendrawada 2025 and Rossi 2021 ChIP-exo only, the original authors'
peak-calling scores as an alternative to the promoter-region-summed enrichment score.

## Structure

The sidebar has controls shared across all three workspace tabs, plus a block of
tab-specific controls that changes depending on which inner tab is active:

- **Execute Analysis** button (always shared).
- **Top N** numeric input (default 25, range 1-500, step 5) -- the number of
  top-binding-ranked promoters per regulator considered when computing percent
  responsive.
- **Responsiveness** radio group: "Relaxed" (default) applies a uniform p-value < 0.05
  threshold to every dataset; "Stringent" uses each dataset's own
  effect-size/p-value thresholds (e.g. degron uses |log2FoldChange| > 0.38 and
  padj < 0.1; kemmeren uses |Madj| > 0.77 and pval < 0.05). Both presets are defined in
  `DEFAULT_RESPONSIVENESS_PRESETS` in `tfbpshiny/utils/vdb_init.py`.

Tab-specific sidebar controls:

- **Compare Datasets**: "Binding Method" select (Promoter Enrichment / Peaks --
  "Peaks" only applies to datasets that have a peak-calling variant, currently rossi
  and chec_m2025) and "Promoter Set" select (Kang / Mindel / 500bp / Intergenic;
  default Kang).
- **Compare Promoter Definitions**: "Promoter Sets" checkbox group (all four sets;
  default all checked).
- **Compare Analysis Methods**: "Binding Dataset" select, populated only with binding
  datasets that have a peaks variant (rossi, chec_m2025), and "Promoter Set" checkbox
  group (default only Kang checked).

The workspace has three tabs (`comparison_inner_tabs`):

- **Compare Datasets** -- a binding-by-perturbation matrix. Each cell shows the median
  percent of top-N binding targets (by the selected Binding Method/Promoter Set) that
  are transcriptionally responsive in that perturbation dataset, colored on a white
  (0%) to green (100%) scale. Clicking a row header selects that binding dataset;
  clicking a column header selects that perturbation dataset. Selecting either shows a
  box plot below the matrix where each point is one
  (regulator, binding sample, perturbation sample) tuple's percent-responsive value.
- **Compare Promoter Definitions** -- one card per active perturbation dataset. Each
  card is a table with binding datasets as rows and the selected promoter sets as
  columns, cells showing median percent responsive (1 decimal place) on the same
  green color scale.
- **Compare Analysis Methods** -- one card per active perturbation dataset, scoped to
  the single binding dataset chosen in the sidebar. Rows are scoring variants
  (Promoter Enrichment per selected promoter set, plus Original Peaks when available),
  columns/cells follow the same layout and color scale as the other tables.

All three tabs read from a pre-materialized `topn_results` table in DuckDB rather than
computing percent-responsive live; "Execute Analysis" triggers the (re)fetch.

## first load

Defaults: Top N = 25, Responsiveness = Relaxed, Binding Method = Promoter Enrichment,
Promoter Set = Kang, all four promoter sets checked on the Promoter Definitions tab,
only Kang checked on the Analysis Methods tab, and the active binding/perturbation
datasets from the select datasets page.

Results start out marked stale, so the Execute Analysis button renders at full
color/opacity (it is only dimmed once results are current and nothing has changed
since). Each tab's table/matrix shows "Click Execute Analysis to compute." until the
button is clicked. If no binding or no perturbation dataset is active, a message above
the tabs reads "Select at least one binding and one perturbation dataset." There is no
separate "please wait" status message while data is fetching -- the only feedback is
that the Execute Analysis button is disabled (`pointer-events: none`, opacity 0.35)
once results are current, and stays clickable while results are stale.

## usage

Changing Top N, Responsiveness, or any tab-specific control (Binding Method, Promoter
Set, included Promoter Sets, Binding Dataset) marks results stale and re-enables the
Execute Analysis button (full color). Changing the active datasets or filters on the
select datasets page does the same. Clicking "Execute Analysis" fetches fresh data for
all three tabs, marks results current, and dims the Execute Analysis button again. The
user can change settings and click Execute Analysis as many times as they like.

On the Compare Datasets tab, clicking a different row or column header swaps which
dataset's distribution is shown below the matrix without requiring Execute Analysis,
as long as results are not stale; if results are stale the distribution area also shows
"Click Execute Analysis to compute." Before any row/column has been selected, the
distribution area reads "Click a row header to view distributions for a binding
dataset, or a column header to view distributions for a perturbation dataset."

## edge cases

- No data for a given binding/perturbation/promoter-set combination: the matrix or
  table cell shows "—" and, on the Compare Datasets tab, the distribution area shows
  "No data for the selected datasets."; the other two tabs show "No data for the
  selected combination."
- No perturbation datasets active: the Compare Promoter Definitions and Compare
  Analysis Methods tabs show "No perturbation datasets selected." instead of any cards.
- No datasets at all selected for the matrix: "No datasets selected."

## impact on other pages

None
