# Changelog

All notable changes to this project will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added

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
  reference publication's method, from `BrentLab/mahendrawada_2025`'s
  `*_peaks` configs). All ranked by `max_score`.
- `build_binding_index` in `modules/comparison/queries.py`: derives every
  binding dataset's label, promoter set and method from `dataset_registry`,
  plus a `(primary, promoter_set_id, binding_method_id) → db_name` lookup.
- DTO (direct target overlap) restored as a second Comparison metric, selectable in
  the sidebar alongside Top-N. Reports the percentage of regulators whose bound and
  responsive target sets overlap more than chance (empirical p < 0.01), out of every
  regulator shared by the two datasets. Reuses the existing promoter-definition and
  binding-method tables, so no new tabs.
- `sample_regulator` table in the materialized database: `(db_name, sample_id) ->
  regulator_locus_tag` over every `*_meta` table carrying a regulator column. Resolves
  DTO's regulator (its source ships only composite identifiers) and supplies the DTO
  denominator.
- `fetch_dto_results` in `modules/comparison/queries.py`, plus a `pr_ranking_column`
  sidebar selector (`log2fc` default, or `pvalue`).

- **Figures page** with publication figures computed live from the materialized
  database: rank vs. response curves (featured TF plus an all-TF small-multiples
  grid), percent-responsive box plots at a selectable top-N cutoff, DTO significance
  counts and fractions on two scales, and Venn diagrams of DTO agreement across
  binding datasets. Each figure states the TF intersection it is drawn over.
- `tfbpshiny/utils/figure.py`: shared plotly styling (`apply_figure_style`), HTML
  embedding that reuses the bundled plotly.js (`figure_html`), a matplotlib->inline-PNG
  bridge for the Venn diagrams, and per-dataset colour maps.

- Figures page gains figure 3 (response rate and bound-set size over the authors' own
  binding call, for the two datasets that publish one) and figure 6 (top-N target
  overlap enrichment between same-type datasets, summarised per TF with 1/N weighting).
- `topn_agreement` materialized table: per-regulator top-N set overlap between
  same-datatype dataset pairs, at ten log-spaced cutoffs to 500. Perturbation datasets
  are ranked by absolute effect so knockout and overexpression are comparable. Log
  enrichment is derived at read time, so the gene-universe constant can change without
  a rebuild.
- `top_n = 0` sentinel rows for the peak datasets, meaning "every authors'-bound
  target, no rank cutoff" -- `n` then carries the size of the authors' bound set.
- `--preset {Relaxed,Stringent}` on `tfbpshiny materialize`, repeatable and
  **defaulting to both**, so the Comparison page's Relaxed/Stringent selector has data
  on either setting. Each preset contributes the (effect, pvalue) pair that *that*
  perturbation dataset uses, so the two presets together need only 1-2 pairs per
  dataset where a cross product of their four distinct pairs would materialize eight.
  Previously Relaxed was stored only because the default thresholds happened to equal
  it; it is now added explicitly.
- SVG export on every figure. Plotly figures save SVG rather than PNG from the
  modebar camera button, with a per-figure filename. The Venn diagrams have no
  modebar, so they carry an explicit "Download SVG" link instead -- right-clicking a
  data-URI image behaves inconsistently across browsers and yields no useful
  filename.

### Changed

- **Figure 6 can compare promoter definitions and calling methods, not just assays.**
  A "Choose datasets to compare" panel below the figure — collapsed by default — lists
  every binding and perturbation dataset; each pair among the selected ones is drawn.
  The default selection is promoter enrichment over the **500 bp start-codon** window
  (`callingcards_500bp`, `rossi_500bp`, `chec_m2025_500bp`), so the assays are compared
  on one promoter definition rather than on whichever happened to be each dataset's
  primary — which was Kang, without saying so. Harbison has no 500 bp variant and so is
  not in the default; select it to include it, accepting that it brings its own
  promoter definition.
- `topn_agreement` now materializes every dataset pair rather than only the primaries,
  which is what makes the selector possible: 21 binding datasets → 210 pairs where
  there were 6. The authors' original peak calls (`rossi_peaks`, `chec_m2025_peaks`)
  are excluded — their regions come from the publication's own pipeline rather than a
  fixed upstream window, so a pair involving one differs in both the caller and the
  region and cannot be attributed to either. The promoter-set-matched re-calls carry
  the same information against a defined window and are kept.
- Figure 6's pair labels are built from `base_label` + promoter set + method
  (e.g. "2021 ChIP-exo 500 bp peaks"). `base_label` alone is shared by every variant
  of an assay, so a promoter-set comparison legended as "ChIP-exo vs ChIP-exo".
- Figure 6's two panels split the row 50/50: neither fixes a `layout.width`, so the
  flex container sizes them, with `responsive: true` in the plotly config so they
  reflow. A 520px floor keeps the curve from collapsing on narrow viewports.
- Figures 1 and 6 draw their legend inside the plotting area (top right, translucent)
  rather than outside. Both plot quantities that fall from left to right, so that
  corner is empty, and an outside legend was taking width the curves needed.

- Figures 3 and 4 are split into two rows (A and B) with one y axis each, replacing
  the single row of twin-axis panels. A count beside a percentage, or a response rate
  beside a target count, invited reading one against the other's scale and never made
  clear which axis a given box belonged to.
- Figure 6's line plot is widened to 1000px and its box plot narrowed to 640px: the
  curve carries six overlapping dataset-pair series and was unreadable at the shared
  container width, while the box plot beside it needs far less room.

- Figures page gains a Responsiveness selector (Relaxed / Stringent / Authors). All
  figure queries now pin `criteria` and the preset's `(effect, pvalue)` pair
  explicitly: since the criteria and preset additions `topn_results` holds 2-3 rows
  per key, and a query that does not pin them medians across incompatible scoring
  definitions -- for `rossi` x `kemmeren` at top 25 that read 0.0% instead of
  Relaxed's 16.0%.

- Figure 4 is given an explicit width and angled category labels; at container width
  the three panels squeezed the dataset names into each other.

- The Comparison tab no longer has an **Execute Analysis** button; tables recompute
  live as sidebar controls change, matching the Binding and Perturbation modules.
  Dataset selection stays batched behind Apply Changes on the selection page, so this
  does not mean a refetch per checkbox there. A busy indicator replaces the button as
  the signal that work is in flight.
- Sidebar controls belonging to one metric (Top N, Require full overlap and
  Responsiveness for Top-N; perturbation ranking for DTO) are rendered per metric
  rather than shown and ignored.

- Comparison module's Top N sidebar control is now a fixed-choice selector
  (10 / 25 / 50 / 75 / 100) instead of a free numeric input, matching the fixed
  set of `--top-n` values now materialized by `tfbpshiny materialize` by default.
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

### Removed

- The `criteria` column on `topn_results`, and with it every row scored from a
  perturbation dataset's own `responsive` boolean. That column is deprecated upstream
  and scheduled for removal, and the `Stringent` preset already holds each dataset's
  published criteria, so the second scoring path was redundant. Responsiveness is now
  decided by `(effect_threshold, pvalue_threshold)` alone. **Requires a rebuild** —
  see the Fixed entry below for what a stale database does.
- The `Authors` option from the Figures page Responsiveness selector, which selected
  those rows. `Relaxed` and `Stringent` remain.
- `has_criteria()`, replaced by `has_top_n()` — figure 3's guard is really about
  whether the `top_n = 0` rows exist.
- `rossi_macs2_peaks` and `chec_m2025_macs2_peaks` binding datasets. Their
  upstream HuggingFace configs (`macs2_annotated_peaks_combined`,
  `macs2_standard_peaks`) were deleted and replaced by the four
  promoter-set-matched peak configs in each repo.
- Dead `BINDING_CONFIGS` dict in `modules/comparison/queries.py`, superseded by
  `BINDING_TOPN_CONFIGS` in `materialize/comparison/topn.py`.

### Fixed

- **Harbison was registered as a Kang promoter dataset, which it is not.** Its regions
  are microarray probes fixed by the ChIP-chip platform, and the source ships
  per-target binding ratios with no signal track to re-summarise over a promoter
  window — so it has no Mindel/500bp/intergenic variants and cannot acquire any. The
  `kang` tag nonetheless placed it in the Kang column of Compare Promoter Definitions,
  inviting a comparison that cannot be made. It now carries a new
  `promoter_sets` entry, `array`, which — like `peaks` — is deliberately absent from
  `PROMOTER_SET_ORDER` and so never becomes a column. Harbison drops out of Compare
  Promoter Definitions (the tab now says why) and is labelled "2004 ChIP-chip Array
  Probes" in figure 6.
- `BindingIndex.resolve_or_self()` keeps a platform-fixed dataset in Compare Datasets
  under every promoter-set selection, since the choice is not one it can express. The
  fallback covers the promoter axis only — asking for Peaks still excludes a dataset
  that has none, so the Peaks view cannot silently show an enrichment dataset.
- **Figure 6's random expectation used `top_n^2` instead of the observed set sizes.**
  `topn_agreement` stores `n_a` and `n_b`, but the read-time enrichment assumed both
  sides contributed exactly N targets. That holds for promoter enrichment and fails for
  peak calling, where the set size is whatever the caller returned: a 30-target peak set
  compared at N=500 was divided by 250,000 rather than 30 × 500, understating enrichment
  ~16-fold and worsening with N — exactly where the curve is read. Fixed at read time,
  no rebuild needed.
- **The Comparison page medianned across two definitions of responsive.** It pins
  `(effect_threshold, pvalue_threshold)` but never pinned `criteria`, and the
  authors'-criteria rows were stamped with the smallest threshold pair — which for
  most datasets *is* the Relaxed pair. Every Relaxed number was therefore a median
  over both row sets: `rossi` x `kemmeren` at top 25 read 0.0% where the
  threshold-scored rows alone give 20.0%. Removing the authors' rows removes the
  ambiguity. The Figures page had been given an explicit `criteria` pin earlier and
  was not affected.
- Reading a database built before that removal now logs a warning at startup
  (`utils/schema_check.py`), since the app no longer filters `criteria` and would
  otherwise silently read low with no traceback and no empty table.
- `_responsive_expr` raises rather than falling back to the deprecated `responsive`
  column when a perturbation dataset declares no effect column in
  `PERTURBATION_DATASET_COLUMNS`.
- **DTO was never materialized.** `coordinator.py` looked for a VirtualDB view named
  `dto`, but labretriever registers comparative datasets (those with a `links:` block)
  as `__dto_parquet` + `dto_expanded` and never creates a bare public view. The guard
  failed on every build and logged a warning, so no `dto` table existed even though
  `comparative_dataset_registry` advertised one. It now reads `dto_expanded` and
  raises instead of skipping silently.
- `dto_schema_sql()` was dead code with zero callers; it is now the DDL actually used,
  so the declared column types and primary key are enforced.
- `_vdb_to_table` names its target columns on insert, allowing a table to have columns
  the SELECT does not supply. The alternative — a NULL placeholder column — would have
  been silently emptied by the existing `dropna(how="any")`.

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
