# Perturbation

The Perturbation page shows how well each pair of active perturbation datasets agree,
regulator by regulator. It analyses only the perturbation datasets that are active on
the Dataset selection page, restricted to their filtered samples.

Perturbation datasets measure the transcriptional response to manipulating a TF: TF
knockouts (Hu 2007, Kemmeren 2014, Hughes 2006 knockout), overexpression (Hughes 2006
overexpression, Hackett 2020) and auxin-inducible degron RNA-seq (Mahendrawada 2025).

## Structure

The page has the same layout as the Binding page:

- **Column**: -log10(p-value), Effect (e.g. log2 fold change) or P-value;
  -log10(p-value) is offered only with Pearson. Default: Effect.
- **Correlation**: Pearson or Spearman. Default: Pearson.
- **Correlation Matrix**: median per-regulator correlation for every active pair,
  read-only.
- **Pair Distribution**: one box plot per active pair, with a "Highlight regulator"
  dropdown.

Correlations are read from the `correlations` table (`comparison_type =
'perturbation'`). Hackett is correlated on `log2_cleaned_ratio`: its responsiveness
column, `log2_shrunken_timecourses`, is 95% exactly zero.

## Behaviour

Everything updates as soon as a control or the dataset selection changes. With fewer
than two active perturbation datasets, the page shows "Select at least two perturbation
datasets to see correlations."

Hughes (both datasets) and Hackett publish no p-value, so a pair involving one of them
has no correlation on the P-value or -log10(p-value) columns; its cell shows "—".

## Effect on other pages

None.
