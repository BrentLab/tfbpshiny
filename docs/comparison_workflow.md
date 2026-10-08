# Binding/Perturbation Comparisons

This page asks how well binding predicts response: for each pair of an active binding
dataset and an active perturbation dataset, how many of a regulator's bound targets
respond when the regulator is perturbed. It also compares, for the same experiment,
the four promoter definitions and the two ways of scoring binding (promoter enrichment
and peak calling).

## Structure

The **sidebar** has:

- **Metric**:
  - *Top-N % responsive*: the median, across regulators, of the percent of each
    regulator's top-N bound targets that are responsive;
  - *DTO % significant*: the percent of regulators shared by the two datasets whose
    bound and responsive target sets overlap more than chance (empirical p < 0.01).
- Controls for the selected metric. For Top-N: **Top N** (10, 25, 50, 75 or 100;
  default 25), **Require full overlap** (on by default: keep only regulator/sample pairs
  whose top-N list is complete after ties are resolved) and **Responsiveness** (Relaxed,
  default: |effect| > 0 and p < 0.05; Stringent: each dataset's published criteria).
  For DTO: **Perturbation Ranking** (log2fc or pvalue).
- Controls for the active tab (below).

The workspace has four tabs:

- **Compare Datasets**: a binding-by-perturbation matrix of the metric, on a white
  (0%) to green (100%) scale. Its controls choose the **Binding Method** (Promoter
  Enrichment or Peaks) and the **Promoter Set** (default Kang). Clicking a row header
  shows the distribution across regulators for that binding dataset against every
  perturbation dataset, and a column header the reverse (Top-N only; DTO gives one value
  per pair).
- **Compare Promoter Definitions**: one table per active perturbation dataset, binding
  datasets as rows and the checked **Promoter Sets** as columns.
- **Compare Analysis Methods**: for one **Binding Dataset** with a peak-calling arm
  (Rossi ChIP-exo or Mahendrawada ChEC-seq), one table per perturbation dataset with
  promoter enrichment and peak calling as rows and the checked promoter sets as columns.
  The two methods are compared over the same regulators: a regulator missing from either
  method in a column is left out of both. **Common regulators only** further restricts
  each table to regulators present in every cell.
- **Method × Promoter Model**: the pooled OLS of percent responsive on method, promoter
  set and assay, with regulator fixed effects and regulator-clustered standard errors,
  fitted when the database is built. One panel per perturbation dataset, for the
  selected Top N and Responsiveness.

Collapsible sections above the tabs explain the binding methods and the four promoter
definitions.

All values are read from tables computed when the database is built (`topn_results`,
`dto`, `method_promoter_model_*`).

## Behaviour

Tables update as soon as a control or the dataset selection changes; a busy indicator
shows while a fetch runs. If no binding or no perturbation dataset is active, the page
shows "Select at least one binding and one perturbation dataset." A combination with no
data shows "—" in its cell; a tab with nothing to show says "No data for the selected
combination." (or "No data for the selected datasets." for the Compare Datasets
distribution).

## Effect on other pages

None.
