# Binding

The Binding page shows how well each pair of active binding datasets agree, regulator
by regulator. It analyses only the binding datasets that are active on the Dataset
selection page, restricted to their filtered samples.

## Structure

The **sidebar** has two controls:

- **Column**: which score the correlations are computed on: -log10(p-value), Effect
  (e.g. enrichment) or P-value. -log10(p-value) is offered only with Pearson: Spearman
  is rank-based, so it would equal the P-value result, and it is not materialized for
  Spearman. Default: P-value.
- **Correlation**: Pearson or Spearman. Default: Spearman.

The **workspace** has two sections:

- **Correlation Matrix**: an upper-triangular matrix over the active binding datasets.
  Each cell shows the median, across regulators, of the per-regulator correlation for
  that pair, to three decimal places, or "—" when the pair has no data. The matrix is
  read-only.
- **Pair Distribution**: one box plot per active pair; each point is one regulator's
  correlation, with the regulator's name on hover. A "Highlight regulator" dropdown,
  listing every regulator present in any pair, marks that regulator in black on every
  plot.

Correlations are computed when the database is built (the `correlations` table,
`comparison_type = 'binding'`); the page reads and aggregates them.

## Behaviour

Everything updates as soon as a control or the dataset selection changes; there is no
apply step. With fewer than two active binding datasets, the page shows "Select at least
two binding datasets to see correlations." If the highlighted regulator is no longer
present after a change, the dropdown falls back to the first regulator alphabetically.

## Effect on other pages

None.
