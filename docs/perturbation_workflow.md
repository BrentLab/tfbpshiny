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

## Structure

There is no dataset multi-selector in the sidebar; the perturbation datasets analyzed
are exactly those selected (and filtered) on the select datasets page. The sidebar has
a "Column" radio group (choices: -log10(p-value), Effect, P-value; default Effect) --
this control is currently a UI-only placeholder and is not read by the server logic, so
changing it has no effect on the analysis. The "Correlation" radio group selects
Pearson or Spearman; the default is Pearson. An "Execute Analysis" button sits above
these controls.

The workspace displays two tabs: "Correlation Matrix" and "Pair Distribution". Pairwise
correlations are pre-computed and stored in the database (a `correlations` table,
`comparison_type="perturbation"`); the page queries and aggregates them rather than
computing correlations live.

The "Correlation Matrix" tab shows an upper-triangular matrix of all active perturbation
dataset pairs. Each cell is a clickable button (stable id `corrpair_<db_a>__<db_b>`)
showing the median per-regulator correlation for that pair to three decimal places, or
"—" if there is no data for the pair. Clicking a cell toggles whether that pair is
selected (visual highlight via a `.matrix-cell-active` class) and queues it for the Pair
Distribution tab. The diagonal and lower triangle are rendered as empty grey
placeholders.

The "Pair Distribution" tab shows one box plot per *committed* pair (see Usage). Each
point in a box plot is one regulator's correlation value for that pair, jittered, with a
tooltip showing the regulator's display name and the correlation value. A "Highlight
regulator" dropdown (populated from regulators present in the committed pairs) overlays
the selected regulator's point on every box plot in black. Box plots fully re-render on
regulator-selection changes; there is no in-place FigureWidget update.

## first load

The sidebar defaults to Effect (no effect on computation) and Pearson. Because
correlations are pre-computed and fetched reactively (not via an extended task), the
Correlation Matrix tab already shows live median-correlation values for every active
pair on first load -- the user does not need to click Execute Analysis to see the
matrix populate. The Pair Distribution tab shows "Click a cell in the Correlation
Matrix to view its distribution." until at least one pair has been selected and
committed.

If fewer than two perturbation datasets are active, the page shows "Select at least
two perturbation datasets to see correlations." above the tabs, and the Correlation
Matrix tab shows the same message in place of the matrix.

## usage

Changing dataset filters or the active perturbation dataset set on the select datasets
page takes effect immediately and automatically -- pair selections reset to "all active
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
regulator's point across all currently rendered box plots. If the previously selected
regulator is not present after a dataset/filter change, the dropdown falls back to the
alphabetically first available regulator.

Not all perturbation datasets have a p-value column (`hughes_overexpression`,
`hughes_knockout`, and `hackett` do not). There is currently no warning surfaced for
this in the UI -- the "Column" selector that would otherwise let a user pick p-value is
a UI-only placeholder with no effect on the analysis.

## impact on other pages

None
