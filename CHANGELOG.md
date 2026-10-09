# Changelog

All notable changes to this project will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.2.0]

### Changed

- **Rebuild to pick up corrections made to the HuggingFace datacards.** The
  Calling Cards Kang analysis set pointed at the Mindel parquet, so
  `callingcards_kang` in the current database holds the Mindel analysis set
  (5,351 targets); it now reads its own file (6,708 targets), and every table
  computed from it changes on rebuild. The `responsive` column was removed from
  every perturbation dataset. The app never read it, so only
  `dataset_column_metadata` loses rows.
- Figure 3 is a scrolling window, three perturbation datasets visible at a time with
  panels as wide as figure 1's; each panel keeps its own y axis.
- Figure 1's axes run from -2 to 102 on y and 0 to 102 on x, so a point at 0%,
  100% or n = 100 is not cut off by the edge.
- Figure 3A's y axis runs from -2 to 102 so points at 0% and 100% are not cut off.
  The Venn diagrams (figures 4, 5 and 10) name their sets in a legend under the
  diagram instead of beside each circle, where the labels ran into each other when
  circles sat close together or did not overlap.
- **Rebuild required.** `Stringent` responsiveness is one rule for every
  perturbation dataset: `|effect| > 0.77` (log2(1.7)) and `pvalue <= 0.05`, each
  on the dataset's own effect and p-value column (`padj` for Degron). Datasets
  with no p-value column (Hackett, Hughes) use the effect threshold alone. The
  earlier per-dataset values are gone: Degron `(0.38, 0.1)`, Hackett and Hughes
  `(0.1 / 1.0, 0.05)`, Hu/Reimand `(0.0, 0.05)`, other datasets `(1.0, 0.05)`.
  The p-value comparison is now `<=` in both presets (it was `<`), so `Relaxed`
  also changes for any row whose p-value is exactly 0.05.
- The default Hackett filter is the 30-minute time point (it was 45). It has one
  sample per regulator, for 196 regulators (45 minutes had 193).
- **Rebuild required; labretriever 1.1.5.** ChEC-seq `Carbon source` and
  `Temperature` follow each sample's condition. They were the dataset-wide
  default (glucose, 30) for all 197 samples, so the filter modal's narrowing of
  conditions by carbon source or temperature had nothing to act on. The
  galactose induction is "raffinose, galactose", the raffinose control
  "raffinose" and the heat shock 37; every other condition is glucose at 30.
  The collection config maps them as `field: condition` plus
  `media.carbon_source.compound` / `temperature_celsius`, like Harbison, which
  labretriever 1.1.5 resolves with the documented precedence (field-level, then
  config-level, then top-level `experimental_conditions`). The minimum version is
  now `labretriever ^1.1.5` in `pyproject.toml` and in the requirements file the
  Dataset selection export writes. The database holds the same ChEC-seq values as
  the earlier workaround produced. The same labretriever fix corrects Harbison
  `Temperature`, which was 37 for all 352 samples and is now 30 for the 346 that
  are not the heat shock.
- `FIELD_TYPE_OVERRIDES` is defined once, in `utils/vdb_init.py`; the Dataset
  selection modules had imported two identical copies. The `temperature_celsius`
  entry, which matched no column, is removed. `docs/development.md` and
  `CLAUDE.md` say where to hide a column from the filter modal
  (`HIDDEN_FILTER_FIELDS`).
- The filter modal opens on the conditions that co-occur with the dataset's
  other characteristics as set by its filters, and offers every condition when
  those characteristics do not vary. Previously a dataset whose characteristics
  were constant (ChEC-seq) offered only the conditions already selected, so
  `standard` was the only checkbox.
- **Rebuild required (schema version 4).** `dataset_column_metadata` gains
  `description` and `level_definitions`, labretriever's column metadata. The
  Dataset selection filter modal uses them again, as it did when it read from
  VirtualDB: experimental-condition columns are checkboxes labelled
  "definition (level)", yes/no toggles carry the column description, the modal
  opens with other characteristics pre-set to the values the current filters
  imply, and selecting e.g. a carbon source narrows the condition checkboxes,
  intersecting every characteristic's selection. Since the move to the
  materialized database the modal had shown bare selectizes with no labels and
  the cascade had updated controls that were not there.
- **Rebuild required (schema version 3).** `dataset_registry` gains a
  `description` column, labretriever's dataset description (the collection
  config's, else the DataCard's). The Dataset selection page shows it again as
  the tooltip on each dataset's name; the tooltips had been empty since the page
  moved from VirtualDB to the materialized database.
- DTO is named for what it is, dual threshold optimization, in the Comparison
  metric tooltip, the figure 4 heading, the `comparative_dataset_registry`
  description and the docs. Earlier text called it "direct target overlap" or
  "directional transcription overlap".
- `shinywidgets` is no longer a dependency; nothing imported it.

- **Rebuild required (schema version 2).** Dataset identity and presentation are
  declared once, as labretriever `tags` in `brentlab_yeast_collection.yaml`,
  read by `materialize` through `VirtualDB`; the promoter-set and binding-method
  vocabulary is `PROMOTER_SETS` / `BINDING_METHODS` in `tfbpshiny/datasets.py`,
  with promoter-set descriptions from labretriever's genome-resources region
  sets. The `dataset_registry`, `promoter_sets` and `binding_methods` tables are
  generated from these instead of hand-written SQL, and gain `color`,
  `reference` and `peak_calling_note` columns, so the app reads labels, colours,
  tooltips and notes only from the database. HF coordinates come from VirtualDB.
  The Comparison page's label, colour and note dicts, the figure palettes and
  the duplicated dataset lists are gone; plot functions take their palette as an
  argument. Label changes: promoter set "500 bp" is now "500bp" everywhere, and
  the Hughes knockout dataset is "2006 TFKO" everywhere (it was "2006 Knockout"
  in the registry and the figures). The YAML's own tags, which disagreed with
  the registry (e.g. degron's assay was `ChIPexo`), now match it.
- **Rebuild required (schema version 1).** Every computed table now also carries
  plain identity columns beside its composite `source_sample` key: `binding_db`,
  `binding_sample_id`, `perturbation_db`, `perturbation_sample_id` on
  `topn_results` and `method_promoter_model_topn`; `db_a`, `sample_a`, `db_b`,
  `sample_b` on `topn_agreement` and `correlations`; `db_name`, `sample_id` on
  `topn_target_sets`. Readers select by name instead of reconstructing a
  `repo;config;` prefix and joining with `LIKE`. The build stamps
  `tfbpshiny.datasets.SCHEMA_VERSION` into a new `schema_version` table; the app
  shows a banner on every page, and the figures refuse to draw, when the stamp
  does not match. Verified by rebuilding and fingerprinting every table: identical
  to the previous build on the original columns.
- Per-dataset facts are declared once, in `tfbpshiny/datasets.py` (measurement
  columns, promoter-set and method levels, top-N choices, preset names, gene
  universe, DTO threshold, schema version). The Comparison and Figures pages build
  their choice lists from it; the figures' promoter-set and method axis labels
  come from the `promoter_sets` / `binding_methods` tables.
- The two Calling Cards / Harbison authors'-threshold generators are one
  `materialize/comparison/authors_bound.py` driven by `AuthorsBoundConfig`; the
  materializer's public names are `exec_static`, `vdb_to_table`, `stage_topn`,
  `stage_method_promoter_topn` and `HARBISON_DEDUP_CTE`. The underscore names
  (`_exec_static`, `_vdb_to_table`, `_method_promoter_topn_staged`,
  `_HARBISON_DEDUP_CTE`) are removed; import the public names.
- The Comparison and Figures workspace servers are split into one file per tab
  or figure under `server/`, wired from a thin `workspace.py`; output ids are
  unchanged and an end-to-end render snapshot (`tests/e2e/test_outputs_render.py`)
  is identical before and after.
- Materialize internals, with the database unchanged: `build_method_promoter_panel`
  receives the expanded default filters once per build rather than recomputing
  them for every cell; `vdb._conn` is touched only by `_stage_table` and
  `_drop_table`; CLI arguments are read directly; and `target_sets_select_sql`
  takes `drop_null_scores`, so a dense peak dataset added to figure 10 would not
  pad its sets with no-peak promoters. `dto_venn_figure` returns
  `(figure, proportional)` instead of setting an attribute on the figure.
- Tests: `test_figures.py` is split into `test_figures_plots.py`,
  `test_figures_queries.py` and `test_figures_fig10.py`. The per-variant top-N
  query used as the oracle for the staged builder lives in
  `tests/unit/_topn_oracle.py`. `tests/unit/_collection.py` gives tests a
  VirtualDB stand-in over the packaged collection config.
- Documentation describes the app as it is. The four page guides
  (`docs/*_workflow.md`) are rewritten for the current controls: no Execute
  buttons, automatic updates, the read-only correlation matrix, the Comparison
  page's Metric selector and four tabs, and staged Apply Changes on the
  selection page. `docs/materialized_db_schema.md` is rewritten to the current
  tables, columns, row counts, CLI options and example queries.
  `docs/development.md`, `docs/sql_operations.md` and `CLAUDE.md` are corrected
  against the code. The README gains a table of contents, the pip-install
  config path and links to the docs.
- Comments and docstrings describe what the code does, not how it changed;
  change history is kept here. `CLAUDE.md` states this as a rule.

- **Rebuild required.** Re-run `tfbpshiny materialize` (about 16 minutes against
  HuggingFace, `correlations` included) so the stored tables follow the changes
  below. Affected: `topn_results`, `topn_agreement`, `topn_target_sets`,
  `method_promoter_model_*`, the peak-calling `_meta` tables (ChEC-seq peak
  variants go from 196/177 to 197/178 samples/regulators, the data now being
  complete) and `dataset_column_metadata`. Schemas are unchanged.
- **Expect the method contrast to move.** With the zero-imputation gone (below),
  the promoter-enrichment-minus-peak-calling coefficient at top 25, Relaxed,
  with the full-overlap floor on, shifts toward peak calling in every
  perturbation dataset (percentage points, before -> after): degron -0.09 ->
  -0.73, hackett +0.24 -> -1.54, hu_reimand -0.43 -> -0.95, hughes_knockout
  -1.23 -> -2.98, hughes_overexpression +0.81 -> -1.67, kemmeren +0.68 -> -0.57.
  The old imputation scored a regulator with no usable peak-calling list as 0%,
  which favoured promoter enrichment. Compare floor on and off in the notebook
  before relying on the contrast.
- **Recalled peak calls are now dense; the app ranks them accordingly.** The
  promoter-set-matched peak datasets (`rossi_peaks_*`, `chec_m2025_peaks_*`)
  report every promoter for every sample, with a NULL score where no peak
  qualified. A NULL now ranks as a score of 0 (`no_signal_value` in
  `BINDING_TOPN_CONFIGS`), below every real score. Note the two peak scores are
  on different scales: Rossi `max_score` is MACS -log10(q) (>= 1), while the
  ChEC-seq BED score is HOMER's **normalized tag count** (89 to ~460,000), not
  -log10(q) as the ChEC-seq datacard states, so they must not be compared across
  datasets. Rossi's 9 regulators with no peak rows at all (HTB2, HHF1, HHT1,
  UPC2, RTF1, IES3, HHF2, HHT2, MKS1) drop out of the method comparison.
- **Top-N tie rule: a tie group is in the top N only if its average rank is
  within N** (all binding datasets; `tie_rule="avg_rank"` in
  `topn_pair_select_sql*`, `"rank"` reproduces the old `RANK() <= N` exactly). A
  large group straddling the cutoff now drops out, so `n` can be below N, and a
  group kept whole can push `n` above N. The giant no-signal group never
  qualifies unless the pool is tiny. Equivalence was checked first: legacy mode
  reproduced the previous output exactly (4,382 of 4,382 rows, and every stored
  row of the unaffected pairs). Where the old list was exactly N the new output
  is identical.
- **"Require full overlap" now means `n >= top_n`** (a complete list after the
  tie rule) instead of the pool-size test `n_intersecting_targets >= top_n`,
  which is vacuous on dense data.
- **Figures 6 and 10 keep exact-N `ROW_NUMBER` sets** (tiebreak
  `target_locus_tag`), but only *scored* rows of the recalled peak datasets are
  ranked (`drop_null_scores_*` in `agreement_pair_select_sql`); otherwise a
  regulator with fewer than N peaks would be padded to N with no-peak promoters.
  Verified: the new builder on the dense tables equals the old builder on the
  equivalent sparse tables.
- **The method x promoter-set model and the method comparisons no longer borrow
  from promoter enrichment.** Removed
  `impute_missing_peak_calling_regulators(_percent)`: a regulator with no usable
  peak-calling list was previously scored as 0% responsive using the matching
  enrichment row. Methods are now **paired** instead
  (`pair_methods_on_regulators`): within each assay x promoter set a regulator
  counts only where both methods have a row. The shared candidate pool is built
  from all eight views of an assay, not from enrichment alone. Affects the model
  tables, the Comparison method table and figures 7-9.
- `tmp/topn_method_regression.ipynb` calls the app's own functions again (no
  standalone copy), reports the HuggingFace revisions it used, writes
  `method_promoter_lm_data.csv` (floor on) and
  `method_promoter_lm_data.nofloor.csv`, and cross-checks the no-floor fits
  against the stored model tables (agreement to ~3e-13).
  `method_promoter_model.py` gains `apply_full_overlap_floor`.
- `chec_m2025_peaks` (the authors' ChEC-seq peak calls) declares a constant
  `Experimental condition = 'standard'` column in the collection yaml (a
  labretriever `expression` mapping), so the default ChEC-seq filter applies to
  it like every other variant. Rebuild the database (or its
  `chec_m2025_peaks_meta` / `dataset_column_metadata` rows) to pick it up.
- The Featured TF dropdown is sorted alphabetically by regulator symbol rather
  than by locus tag.
- Figure 5's Venn circles use the same per-dataset colours as figures 1-4.
  Figure 2's y axis is padded to -2..102 so points at exactly 0% and 100%
  are drawn whole, and figure 3's two rows are spaced further apart.
- **The 500 bp start-codon window is now the primary promoter definition for
  every promoter-enrichment assay.** `callingcards_500bp`, `rossi_500bp` and
  `chec_m2025_500bp` carry `is_primary = TRUE`; the Kang quantifications
  (`callingcards_kang`, `rossi`, `chec_m2025`) become variants of them, and
  every other variant -- including the peak calls -- repoints its
  `primary_db_name` accordingly. 500 bp is the one definition all three assays
  share, so making it primary is what lets the figures compare assays without
  silently comparing promoter definitions at the same time. Harbison stays
  primary on `array`: its regions are microarray probes, so it has no 500 bp
  variant and cannot acquire one. `PRIMARY_DATASETS` and
  `DEFAULT_ACTIVE_DATASETS` follow, so the Dataset Selection page now offers the
  500 bp datasets. **Requires a rebuild.**
- The figures' `BINDING_ORDER`, `DTO_BINDING_ORDER` and
  `AGREEMENT_DEFAULT_BINDING` all name the 500 bp datasets, so figures 1-6 are
  drawn on one promoter definition unless figure 6's picker is used to choose
  otherwise.
- `dataset_labels()` covers every dataset rather than only the primaries. Figure
  6's picker can select any variant, and a figure constant can legitimately name
  a non-primary; leaving those unlabelled made the `BINDING_COLORS` lookup
  return `None`, which plotly rejects outright rather than degrading.
- **Figure 6's per-TF summary weight decays exponentially rather than as `1/N`,
  and the decay is now a slider.** Each cutoff is weighted `2 ** (-N /
  half_life)`, so `half_life` is the increase in N over which a cutoff's
  influence halves -- in the same units as N, which is what makes the control
  interpretable. The slider runs 10-200 in steps of 10, matching
  `AGREEMENT_TOP_N`, and defaults to 10 (about half the weight on N=10). A
  half-life of 20 reproduces the balance of the old `1/N` weighting (29.3% of
  the mass on N=10, against `1/N`'s 27.8%). Weights are normalised within each
  (pair, regulator) group, so the result stays a weighted *mean* on the
  enrichment's own scale and a regulator missing some cutoffs is not biased low.
  The half-life appears on the y-axis label and in the exported SVG filename, so
  two exports can be told apart. It affects the box plot only; the
  enrichment-vs-N curve is unweighted.
- **Computed floating-point columns are rounded before they are stored**, with
  `--float-decimals N` on `tfbpshiny materialize` (default 9, i.e. ~1e-9; `-1`
  stores raw values). Covers `correlations.correlation` and
  `topn_results.responsive_ratio` -- the values this pipeline calculates. DTO's
  floats are read straight from the source parquet and are never rounded, since
  that would alter published data rather than remove computation noise. The
  constant and its justification live in `materialize/rounding.py`.
- **`topn_agreement` is now reproducible between builds.** `ROW_NUMBER()`
  numbers tied values in scan order, so which targets fell inside a cutoff
  varied per run: two builds of the same database disagreed on `n_intersect` for
  30,829 of 609,450 rows across 219 of 225 dataset pairs, and one pair re-run
  twice in a single process disagreed on 24.4% of its rows. `target_locus_tag`
  is appended as a final sort key, making the ordering total -- `(sample_id,
  regulator_locus_tag, target_locus_tag)` is unique in every dataset, so the
  sort key is total everywhere. Verified: seven previously-unstable pairs,
  including the worst offenders at 24.4%, 34.7% and 26.1%, now return identical
  `n_intersect` on repeat runs.
- Agreement ranking columns can be overridden per dataset without touching
  `topn_results`, via `AGREEMENT_RANK_OVERRIDES`. Calling Cards ranks on
  `log_poisson_pval`, which is computed in log space and so keeps the rows whose
  linear `poisson_pval` underflows to 0. On its own it is only a marginal help
  against ties (measured 28.8%->26.9% kang and mindel, 36.2%->35.2% 500bp,
  50.1%->48.8% intergenic) -- a log is monotonic and cannot separate genuinely
  equal values, and the Calling Cards ties come from discreteness of the Poisson
  computation over small integer hop counts rather than from underflow.
  Determinism comes from the tiebreak.
- Hackett is ranked and correlated on `log2_cleaned_ratio` rather than
  `log2_shrunken_timecourses`, which is 95% exactly zero. This one is decisive
  for ties: live-group collisions at the cutoff fall from up to 999 groups to at
  most 5 across the whole grid. `log2_shrunken_timecourses` remains what defines
  *responsive* in `topn_results`, so this does not change any responsiveness
  call.
- **Calling Cards' primary is renamed `callingcards` -> `callingcards_kang`**
  and its config is now `annotated_feature_reprocess_yiming_analysis`, replacing
  `2026_analysis_set`. All four Calling Cards configs are now explicitly
  suffixed by promoter set; Rossi and ChEC-seq still use bare names for their
  Kang variants. The new config conforms to the schema the other three Calling
  Cards configs already used, which means the primary gains `log_poisson_pval`,
  `poisson_qval` and the hypergeometric columns, and its library-size columns
  are spelled `total_background_hops` / `total_experiment_hops` rather than
  `background_total_hops` / `experiment_total_hops`. Updated in the collection
  YAML (dataset block and the DTO `links:` block), `DATASET_HF_COORDS`,
  `dataset_registry` (including the three variants' `primary_db_name`),
  `BINDING_TOPN_CONFIGS`, `BINDING_DATASET_COLUMNS` in both
  `materialize/comparison/correlations.py` and `modules/binding/queries.py`,
  `PRIMARY_DATASETS`, `DEFAULT_ACTIVE_DATASETS`, and the figures module's
  `BINDING_ORDER` / `DTO_BINDING_ORDER`. All four configs also moved from
  `combined_id` to `gm_id` as the sample identifier, so every `source_sample`
  for Calling Cards changes -- **a rebuild is required** and prior materialized
  databases are not comparable.
- `HIDDEN_FILTER_FIELDS` now hides the hop-count columns for all four Calling
  Cards configs, not just the primary. Only the primary had an entry, so the
  three promoter variants were offering `total_background_hops` /
  `total_experiment_hops` as filter options in Dataset Selection even though
  they are library sizes, not conditions.
- **`topn_results` is computed by scanning each source once instead of once per
  variant.** The build ran `product(binding, perturbation)` on the outside with
  the `(top_n, effect, pvalue)` variants inside, so both parquet sources were
  rescanned for every combination -- about 1170 full scans, with Rossi's 8.7
  M-row config re-read some 60 times. It is now three stages: each perturbation
  dataset is materialized once up front, each binding dataset once as its loop
  iteration begins, and one query per `(binding, perturbation)` pair emits every
  cutoff and threshold pair from a single scan-and-rank. **1170 query units
  become 138, and ~2340 parquet scans become 29.** `n_intersecting_targets` is
  identical across a pair's variants, so it is computed once rather than ~8
  times. What is *not* hoisted: `binding_ranked` joins `intersecting_targets`
  before ranking, so "top 25" means "top 25 of the targets measured in both
  datasets" and the rank genuinely differs per perturbation dataset. Only the
  scan feeding the rank is shared.
- **Figure 6 can compare promoter definitions and calling methods, not just
  assays.** A "Choose datasets to compare" panel below the figure — collapsed by
  default — lists every binding and perturbation dataset; each pair among the
  selected ones is drawn. The default selection is promoter enrichment over the
  **500 bp start-codon** window (`callingcards_500bp`, `rossi_500bp`,
  `chec_m2025_500bp`), so the assays are compared on one promoter definition
  rather than on whichever happened to be each dataset's primary — which was
  Kang, without saying so. Harbison has no 500 bp variant and so is not in the
  default; select it to include it, accepting that it brings its own promoter
  definition.
- `topn_agreement` now materializes every dataset pair rather than only the
  primaries, which is what makes the selector possible: 21 binding datasets →
  210 pairs where there were 6. The authors' original peak calls (`rossi_peaks`,
  `chec_m2025_peaks`) are excluded — their regions come from the publication's
  own pipeline rather than a fixed upstream window, so a pair involving one
  differs in both the caller and the region and cannot be attributed to either.
  The promoter-set-matched re-calls carry the same information against a defined
  window and are kept.
- Figure 6's pair labels are built from `base_label` + promoter set + method
  (e.g. "2021 ChIP-exo 500 bp peaks"). `base_label` alone is shared by every
  variant of an assay, so a promoter-set comparison legended as "ChIP-exo vs
  ChIP-exo".
- Figure 6's two panels split the row 50/50: neither fixes a `layout.width`, so
  the flex container sizes them, with `responsive: true` in the plotly config so
  they reflow. A 520px floor keeps the curve from collapsing on narrow
  viewports.
- Figures 1 and 6 draw their legend inside the plotting area (top right,
  translucent) rather than outside. Both plot quantities that fall from left to
  right, so that corner is empty, and an outside legend was taking width the
  curves needed.
- Figures 3 and 4 are split into two rows (A and B) with one y axis each,
  replacing the single row of twin-axis panels. A count beside a percentage, or
  a response rate beside a target count, invited reading one against the other's
  scale and never made clear which axis a given box belonged to.
- Figure 6's line plot is widened to 1000px and its box plot narrowed to 640px:
  the curve carries six overlapping dataset-pair series and was unreadable at
  the shared container width, while the box plot beside it needs far less room.
- Figures page gains a Responsiveness selector (Relaxed / Stringent / Authors).
  All figure queries now pin `criteria` and the preset's `(effect, pvalue)` pair
  explicitly: since the criteria and preset additions `topn_results` holds 2-3
  rows per key, and a query that does not pin them medians across incompatible
  scoring definitions -- for `rossi` x `kemmeren` at top 25 that read 0.0%
  instead of Relaxed's 16.0%.
- Figure 4 is given an explicit width and angled category labels; at container
  width the three panels squeezed the dataset names into each other.
- The Comparison tab no longer has an **Execute Analysis** button; tables
  recompute live as sidebar controls change, matching the Binding and
  Perturbation modules. Dataset selection stays batched behind Apply Changes on
  the selection page, so this does not mean a refetch per checkbox there. A busy
  indicator replaces the button as the signal that work is in flight.
- Sidebar controls belonging to one metric (Top N, Require full overlap and
  Responsiveness for Top-N; perturbation ranking for DTO) are rendered per
  metric rather than shown and ignored.
- Comparison module's Top N sidebar control is now a fixed-choice selector (10 /
  25 / 50 / 75 / 100) instead of a free numeric input, matching the fixed set of
  `--top-n` values now materialized by `tfbpshiny materialize` by default.
- Comparison module's "Compare Analysis Methods" tab is transposed: each
  perturbation dataset's table now has the four promoter definitions as columns
  and the two binding methods (promoter enrichment, peak calling) as rows, with
  a shared regulator-count footer. The peak-calling row carries a tooltip naming
  the caller. The original authors' peaks are no longer shown in this tab —
  having no fixed promoter window, they do not belong to any column — but remain
  available elsewhere as `rossi_peaks` / `chec_m2025_peaks`.
- The Comparison module reads its binding-dataset labels, promoter sets and
  methods from `dataset_registry` instead of seven hand-maintained dicts
  (`BINDING_LABEL_MAP`, `BINDING_BASE_LABEL_MAP`, `PROMOTER_SET_MAP`,
  `PROMOTER_VARIANT_PAIRS`, `METHOD_BASE_LABEL_MAP`, `SCORING_VARIANT_MAP`,
  `PEAKS_VARIANT_MAP`), which had drifted out of sync with the collection YAML.
- "Compare Datasets" now honours the Promoter Set selector when the Binding
  Method is "Peaks"; previously it ignored it and returned every peak variant.

### Fixed

- The note under figure 4 and the schema document said Harbison has no DTO
  results. The `dto` table holds 3,848 Harbison rows. The DTO figures are still
  drawn over the three 500bp promoter-enrichment datasets, because figure 5's
  Venn diagrams take exactly three, so the note now says Harbison is not
  included and the comments and documentation describe that choice.
- The filter modal for the ChEC-seq primary listed both `condition` and
  `Experimental condition` (the same values under the raw and the standardised
  name) and a `mahendrawada_symbol` selectize with 178 regulator symbols; the
  Rossi modal listed `antibody` and `growth_media`. `HIDDEN_FILTER_FIELDS` was
  keyed by `chec_m2025` and `rossi`, which are not the datasets the selection
  page shows, so nothing was hidden for them. It is now keyed by primary dataset
  and variants inherit it (`hidden_filter_fields`), and a test checks that every
  key of it and of `DEFAULT_DATASET_FILTERS` names a primary. Regulators are
  identified by `regulator_symbol` and `regulator_locus_tag` only. The stored
  `dataset_column_metadata` drops 30 hidden rows; the schema is unchanged.
- The Compare Analysis Methods tab's peak-caller tooltip (MACS / HOMER) was
  keyed by `rossi` / `chec_m2025` but looked up with the primary
  (`rossi_500bp`), so it always showed the generic fallback after the 500bp
  primaries change. It now reads the primary's `peak_calling_note` tag.
- Six samples (three per Hughes dataset: YIL101C, YER161C, YKL109W) were silently
  dropped from `hughes_knockout_meta` / `hughes_overexpression_meta` because the
  materializer discarded any row containing a NULL (their `found_domain` is
  NULL). Only the `correlations` writer drops NaN rows now; the samples are back,
  `sample_regulator` gains six rows, and the Hughes method x promoter-set fits
  gain one regulator.
- Shiny inputs are read through one `utils.inputs.read_input`, which falls back
  to the default only for an input the client has not sent yet (or a value the
  cast rejects); the sixteen `try/except Exception` readers it replaces also
  hid real errors. The Comparison queries log a DB error instead of swallowing it.

- **Default dataset filters now reach every variant of a dataset.** A filter set
  on the selection tab (or by default) is applied to the dataset's promoter-set
  and peak-calling variants as well, through `expand_filters_to_variants` in
  `utils/corr_query.py`, wired into the Binding, Perturbation, Comparison and
  Figures tabs via `analysis_filters` in `app.py`. Previously
  `DEFAULT_DATASET_FILTERS` was keyed `rossi` / `chec_m2025` while consumers
  looked filters up under `rossi_500bp` / `chec_m2025_500bp` and each variant's
  own name, so Rossi and ChEC-seq (and their 12+ variants) were silently
  unfiltered: a regulator could appear up to 14 times in one cell. Filtered,
  every dataset is one sample per regulator. A variant lacking a filter column
  is logged (once) rather than skipped silently; a variant with no metadata
  table at all is skipped quietly.
- **The Figures tab now filters the binding side too.** Figures 1, 2, 3 and 7-9
  (`fetch_rank_response`, `fetch_topn_percent_responsive`,
  `fetch_authors_bound`) applied the sample filter to the perturbation dataset
  only, so a regulator's heat-shock or non-standard-condition binding samples
  were pooled into the medians. Figure 6 (`fetch_agreement`) filtered neither
  side. Both sides now use each dataset's filtered samples, via
  `_per_dataset_sample_clause`. Figures 4-5 (DTO) are not sample-level and are
  unchanged.
- Figure 6 warns at startup when one of its default datasets is not in
  `dataset_registry`. The membership filter in `_agreement_selection` silently
  drops unknown names, so a renamed `db_name` would have quietly shrunk the
  default view instead of failing.
- **Harbison was registered as a Kang promoter dataset, which it is not.** Its
  regions are microarray probes fixed by the ChIP-chip platform, and the source
  ships per-target binding ratios with no signal track to re-summarise over a
  promoter window — so it has no Mindel/500bp/intergenic variants and cannot
  acquire any. The `kang` tag nonetheless placed it in the Kang column of
  Compare Promoter Definitions, inviting a comparison that cannot be made. It
  now carries a new `promoter_sets` entry, `array`, which — like `peaks` — is
  deliberately absent from `PROMOTER_SET_ORDER` and so never becomes a column.
  Harbison drops out of Compare Promoter Definitions (the tab now says why) and
  is labelled "2004 ChIP-chip Array Probes" in figure 6.
- `BindingIndex.resolve_or_self()` keeps a platform-fixed dataset in Compare
  Datasets under every promoter-set selection, since the choice is not one it
  can express. The fallback covers the promoter axis only — asking for Peaks
  still excludes a dataset that has none, so the Peaks view cannot silently show
  an enrichment dataset.
- **Figure 6's random expectation used `top_n^2` instead of the observed set
  sizes.** `topn_agreement` stores `n_a` and `n_b`, but the read-time enrichment
  assumed both sides contributed exactly N targets. That holds for promoter
  enrichment and fails for peak calling, where the set size is whatever the
  caller returned: a 30-target peak set compared at N=500 was divided by 250,000
  rather than 30 × 500, understating enrichment ~16-fold and worsening with N —
  exactly where the curve is read. Fixed at read time, no rebuild needed.
- **The Comparison page medianned across two definitions of responsive.** It
  pins `(effect_threshold, pvalue_threshold)` but never pinned `criteria`, and
  the authors'-criteria rows were stamped with the smallest threshold pair —
  which for most datasets *is* the Relaxed pair. Every Relaxed number was
  therefore a median over both row sets: `rossi` x `kemmeren` at top 25 read
  0.0% where the threshold-scored rows alone give 20.0%. Removing the authors'
  rows removes the ambiguity. The Figures page had been given an explicit
  `criteria` pin earlier and was not affected.
- Reading a database built before that removal now logs a warning at startup
  (`utils/schema_check.py`), since the app no longer filters `criteria` and
  would otherwise silently read low with no traceback and no empty table.
- `_responsive_expr` raises rather than falling back to the deprecated
  `responsive` column when a perturbation dataset declares no effect column in
  `PERTURBATION_DATASET_COLUMNS`.
- **DTO was never materialized.** `coordinator.py` looked for a VirtualDB view
  named `dto`, but labretriever registers comparative datasets (those with a
  `links:` block) as `__dto_parquet` + `dto_expanded` and never creates a bare
  public view. The guard failed on every build and logged a warning, so no `dto`
  table existed even though `comparative_dataset_registry` advertised one. It
  now reads `dto_expanded` and raises instead of skipping silently.
- `dto_schema_sql()` was dead code with zero callers; it is now the DDL actually
  used, so the declared column types and primary key are enforced.
- `_vdb_to_table` names its target columns on insert, allowing a table to have
  columns the SELECT does not supply. The alternative — a NULL placeholder
  column — would have been silently emptied by the existing `dropna(how="any")`.

### Added

- `scripts/snapshot_db.py`, `scripts/diff_snapshots.py` and
  `scripts/snapshot_queries.py`: fingerprint every table of a build and the output
  of every read-side query under the default inputs, so a rebuild or a refactor
  can be diffed against a baseline.
- `components.sidebar_text`; every `empty-state` and `sidebar-text` div goes
  through `components.py` as CLAUDE.md required.

- **Figure 10, "Targets shared between datasets"**: for each comparison type, the
  featured TF's Venn diagram of the targets each dataset ranks in its top N (left)
  beside the distribution across TFs of how many targets each dataset pair has in
  common (right), at the sidebar's Top N. Pair colours match figure 6.
- New `topn_target_sets` table (`materialize/comparison/target_sets.py`): each
  sample's ranked top-100 targets per regulator for the six datasets figure 10
  uses, with duplicate-probe rows collapsed first (Kemmeren and Hackett measure
  some genes more than once). Built under `--skip-topn`'s complement; re-run
  `tfbpshiny materialize`, or insert it into an existing database.

- **Figure 3 now includes Harbison (ChIP-chip)**, with "bound" defined as
  `pvalue <= 0.001` (YPD samples, matching every other Harbison analysis).
  `materialize/comparison/harbison_authors_bound.py` writes `top_n = 0` rows
  into `topn_results` the same way the Calling Cards block does, so
  `tfbpshiny materialize` must be re-run for the figure to show it.

- **New Comparison subtab, "Method × Promoter Model"**, answering what the
  existing descriptive tabs cannot: the relative contribution of peak
  calling vs. promoter enrichment and of the 4 promoter definitions, while
  holding regulator identity and assay constant. A pooled OLS
  (`responsive_ratio ~ method + promoter_set + assay + C(regulator)`) with
  cluster-robust standard errors by regulator, fit once per (perturbation
  dataset, top-N, preset) during `tfbpshiny materialize` and displayed as a
  precomputed, `summary(lm())`-style coefficient table -- no fitting
  happens in the app. Restricted to regulators in the 3-way intersection of
  the perturbation dataset and both binding assays, and to samples allowed
  by the app's default per-dataset filters (e.g. Hackett's 45-minute
  timepoint), matching every other Comparison tab.
- `materialize/comparison/method_promoter_model.py`: panel assembly (16
  cells: 2 methods x 4 promoter sets x 2 assays; Harbison, the authors'
  original peaks, and Calling Cards excluded, each for a different
  structural reason) and the pooled OLS fit.
- Two new tables: `method_promoter_model_coefs` (term, estimate, std error,
  t, p -- filtered to the six terms of interest; the regulator fixed-effect
  dummies are fit but never displayed) and `_fit_summary` (n_obs,
  n_regulators, R², convergence).
- The Method × Promoter Model tab adds no new sidebar selectors: it reuses
  the shared Top N and Responsiveness controls every other Comparison tab
  already reads, and follows the existing
  one-panel-per-active-perturbation-dataset convention.
- `--skip-method-promoter-model` on `tfbpshiny materialize`.
- `n_intersecting_targets` column to the materialized `topn_results` table: the
  uncapped count of shared regulator/target pairs between a binding sample and a
  perturbation sample, independent of the top-N cutoff.
- Comparison module: "Require full overlap" toggle (on by default) that filters
  top-N results to regulator/sample pairs whose raw target overlap meets the
  selected Top N.
- Eight promoter-set-matched peak-calling binding datasets, so peak calling and
  promoter enrichment can be compared over the *same* upstream window:
  `rossi_peaks_{kang,mindel,500bp,intergenic}` (MACS, from
  `BrentLab/rossi_2021`'s `macs_*` configs) and
  `chec_m2025_peaks_{kang,mindel,500bp,intergenic}` (HOMER, replicating the
  reference publication's method, from `BrentLab/mahendrawada_2025`'s `*_peaks`
  configs). All ranked by `max_score`.
- `build_binding_index` in `modules/comparison/queries.py`: derives every
  binding dataset's label, promoter set and method from `dataset_registry`, plus
  a `(primary, promoter_set_id, binding_method_id) → db_name` lookup.
- DTO (dual threshold optimization) restored as a second Comparison metric,
  selectable in the sidebar alongside Top-N. Reports the percentage of
  regulators whose bound and responsive target sets overlap more than chance
  (empirical p < 0.01), out of every regulator shared by the two datasets.
  Reuses the existing promoter-definition and binding-method tables, so no new
  tabs.
- `sample_regulator` table in the materialized database: `(db_name, sample_id)
  -> regulator_locus_tag` over every `*_meta` table carrying a regulator column.
  Resolves DTO's regulator (its source ships only composite identifiers) and
  supplies the DTO denominator.
- `fetch_dto_results` in `modules/comparison/queries.py`, plus a
  `pr_ranking_column` sidebar selector (`log2fc` default, or `pvalue`).

- **Figures page** with publication figures computed live from the materialized
  database: rank vs. response curves (featured TF plus an all-TF small-multiples
  grid), percent-responsive box plots at a selectable top-N cutoff, DTO
  significance counts and fractions on two scales, and Venn diagrams of DTO
  agreement across binding datasets. Each figure states the TF intersection it
  is drawn over.
- `tfbpshiny/utils/figure.py`: shared plotly styling (`apply_figure_style`),
  HTML embedding that reuses the bundled plotly.js (`figure_html`), a
  matplotlib->inline-PNG bridge for the Venn diagrams, and per-dataset colour
  maps.

- Figures page gains figure 3 (response rate and bound-set size over the
  authors' own binding call, for the two datasets that publish one) and figure 6
  (top-N target overlap enrichment between same-type datasets, summarised per TF
  with 1/N weighting).
- `topn_agreement` materialized table: per-regulator top-N set overlap between
  same-datatype dataset pairs, at ten log-spaced cutoffs to 500. Perturbation
  datasets are ranked by absolute effect so knockout and overexpression are
  comparable. Log enrichment is derived at read time, so the gene-universe
  constant can change without a rebuild.
- `top_n = 0` sentinel rows for the peak datasets, meaning "every authors'-bound
  target, no rank cutoff" -- `n` then carries the size of the authors' bound
  set.
- `--preset {Relaxed,Stringent}` on `tfbpshiny materialize`, repeatable and
  **defaulting to both**, so the Comparison page's Relaxed/Stringent selector
  has data on either setting. Each preset contributes the (effect, pvalue) pair
  that *that* perturbation dataset uses, so the two presets together need only
  1-2 pairs per dataset where a cross product of their four distinct pairs would
  materialize eight. Previously Relaxed was stored only because the default
  thresholds happened to equal it; it is now added explicitly.
- SVG export on every figure. Plotly figures save SVG rather than PNG from the
  modebar camera button, with a per-figure filename. The Venn diagrams have no
  modebar, so they carry an explicit "Download SVG" link instead --
  right-clicking a data-URI image behaves inconsistently across browsers and
  yields no useful filename.

### Removed

- The AWS deployment: `compose/` (Dockerfiles, Traefik), `production.yml`,
  `terraform/`, the Dependabot Docker entry and the EC2/Docker documentation.
  The app is deployed to shinyapps.io (moving to Posit Connect).
  `python-dotenv`, used only by the Docker environment, is dropped.
- `tfbpshiny/deprecated/` (4,400 lines that no longer imported), the
  `modules/binding` and `modules/perturbation` `queries.py` shims,
  `utils/sample_conditions.py`, the legacy per-variant top-N path and its
  `--legacy-topn` flag (its SQL survives only as the test oracle), `fetch_dto_pvalues`,
  the `has_top_n` / `table_exists` / `warn_if_stale_topn_schema` probes, and four
  component factories with no caller. `docs/development.md` and
  `docs/sql_operations.md` are rewritten to describe the materialize-then-read
  architecture; the `page_test.py` requirement is dropped.

- The `criteria` column on `topn_results`, and with it every row scored from a
  perturbation dataset's own `responsive` boolean. That column is deprecated
  upstream and scheduled for removal, and the `Stringent` preset already holds
  each dataset's published criteria, so the second scoring path was redundant.
  Responsiveness is now decided by `(effect_threshold, pvalue_threshold)` alone.
  **Requires a rebuild** — see the Fixed entry below for what a stale database
  does.
- The `Authors` option from the Figures page Responsiveness selector, which
  selected those rows. `Relaxed` and `Stringent` remain.
- `has_criteria()`, replaced by `has_top_n()` — figure 3's guard is really about
  whether the `top_n = 0` rows exist.
- `rossi_macs2_peaks` and `chec_m2025_macs2_peaks` binding datasets. Their
  upstream HuggingFace configs (`macs2_annotated_peaks_combined`,
  `macs2_standard_peaks`) were deleted and replaced by the four
  promoter-set-matched peak configs in each repo.
- Dead `BINDING_CONFIGS` dict in `modules/comparison/queries.py`, superseded by
  `BINDING_TOPN_CONFIGS` in `materialize/comparison/topn.py`.

---

## [1.1.0] - 2026-06-15

### Changed

- Deferred the startup data materialization to a background task so the app becomes
  interactive in a few seconds instead of blocking ~30-57s on every cold start.
  Data-querying tabs show an "optimizing" banner and unlock automatically once the
  background materialization completes; queries are gated until then to keep the
  shared DuckDB connection single-threaded.
- Made startup loading banners report accurate cold-start times (up to ~10s for
  initial load, up to ~50s for the background optimization step).
- Moved production (EC2/Docker) and shinyapps.io deployment instructions out of the
  README into `docs/development.md`; the default log level is now `WARNING`.

### Removed

- "Under development" banner from the Home page.

### Fixed

- Diagonal cell sample count in the dataset matrix now reports the total row count
  rather than the distinct sample count.
- Corrected the end-to-end navigation test selectors to match the current UI.
- Packaging fix so `configure_logger` resolves when installed from PyPI/GitHub.

### Updated

- labretriever updated to 1.1.3, which is on bioconda.

---

## [1.0.0] - 2026-06-12

### Added

- Initial public release of TFBPShiny.
- Dashboard interface for exploring transcription factor binding and perturbation
  data from the Brent Lab yeast collection.
- Dataset Selection module with filter controls for binding and perturbation datasets.
- Binding module with correlation and scatter visualizations.
- Perturbation module with correlation and scatter visualizations.
- Comparison module with three subtabs: Compare Datasets (binding vs. perturbation
  matrix), Compare Promoter Definitions (enrichment scores across four promoter sets:
  Kang, Mindel, 500bp, Intergenic), and Compare Analysis Methods (promoter enrichment
  vs. original peaks for ChIP-exo and ChEC-seq datasets).
- `python -m tfbpshiny launch` CLI entry point: downloads the HuggingFace dataset
  cache on first run and serves the app on subsequent runs from the same directory.
  Supports `--cache-dir`, `--skip-initialize`, `--no-materialize`, `--port`, `--host`,
  and `--debug` flags.
- Projected in-memory materialization of dataset views at startup for improved query
  performance; disabled via `--no-materialize` or `TFBPSHINY_MATERIALIZE=0`.
- Docker Compose production stack with Traefik reverse proxy and AWS CloudWatch
  logging.
- shinyapps.io deployment support via `shinyapps_entry.py`.
- Terraform configuration for EC2 provisioning.
