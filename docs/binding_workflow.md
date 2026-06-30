# Binding

This describes the workflow through the binding page. The binding page provides focused
analysis of the selected binding sets. Note that the user must have first selected
datasets on the select datasets page (there are defaults set by the site developer)
in order to have data to analyze on the binding page. The binding data available for
analysis should be only the data that is selected on the select datasets page, including
the filters.

## Structure

The sidebar lets the user select among the active binding datasets (those selected on
the select datasets page) which ones to include in the analysis, via a checkbox group
labeled "Datasets" (all active datasets are checked by default). The sidebar also has
a "Column" radio group (choices: -log10(p-value), Effect, P-value; default
-log10(p-value)) -- this control is currently a UI-only placeholder and is not read by
the server logic, so changing it has no effect on the analysis. The "Correlation" radio
group selects Pearson or Spearman; the default is **Spearman**. An "Execute Analysis"
button sits above these controls.

The workspace displays two tabs: "Correlation Matrix" and "Pair Distribution". Pairwise
correlations are pre-computed and stored in the database (a `correlations` table,
`comparison_type="binding"`); the page queries and aggregates them rather than
computing correlations live.

The "Correlation Matrix" tab shows an upper-triangular matrix of all active-dataset
pairs. Each cell is a clickable button (stable id `corrpair_<db_a>__<db_b>`) showing the
median per-regulator correlation for that pair to three decimal places, or "—" if there
is no data for the pair. Clicking a cell toggles whether that pair is selected (visual
highlight via a `.matrix-cell-active` class) and queues it for the Pair Distribution
tab. The diagonal and lower triangle are rendered as empty grey placeholders.

The "Pair Distribution" tab shows one box plot per *committed* pair (see Usage). Each
point in a box plot is one regulator's correlation value for that pair, jittered, with a
tooltip showing the regulator's display name and the correlation value. A "Highlight
regulator" dropdown (populated from regulators present in the committed pairs) overlays
the selected regulator's point on every box plot in black. Box plots fully re-render on
regulator-selection changes; there is no in-place FigureWidget update.

## first load

All active binding datasets are checked by default. The correlation method defaults to
Spearman. Because correlations are pre-computed and fetched reactively (not via an
extended task), the Correlation Matrix tab already shows live median-correlation values
for every active pair on first load -- the user does not need to click Execute Analysis
to see the matrix populate. The Pair Distribution tab, however, shows "Click a cell in
the Correlation Matrix to view its distribution." until at least one pair has been
selected and committed.

If fewer than two binding datasets are active, the page shows "Select at least two
binding datasets to see correlations." above the tabs, and the Correlation Matrix tab
shows "Click Execute Analysis after selecting datasets."

## usage

Toggling a dataset checkbox or changing dataset filters on the select datasets page
takes effect immediately and automatically -- pair selections reset to "all active
pairs", the matrix refetches, and no Execute click is required. Selecting a different
correlation method (Pearson/Spearman), on the other hand, only marks the analysis as
having pending changes: a banner reading "Pending changes — click Execute Analysis to
update the distributions." appears, and the Execute Analysis button becomes fully
opaque/clickable (it is dimmed by default via the `btn-apply-pending--idle` class).
Clicking a matrix cell also marks the analysis pending in the same way, toggling that
pair in/out of the pending selection without changing the Pair Distribution tab yet.

Clicking "Execute Analysis" commits the pending pair selection and correlation method,
refetches the correlation data, re-renders the Pair Distribution box plots for the
committed pairs, clears the pending-changes banner, and dims the button again.

Selecting a regulator from the "Highlight regulator" dropdown highlights that
regulator's point across all currently rendered box plots. If the user changes the
active datasets on the select datasets page such that the previously selected regulator
is no longer present, the dropdown falls back to the alphabetically first available
regulator.

## impact on other pages

None
