# SQL Operations Reference

Catalogue of the SQL the running app executes against the materialized DuckDB file.
Every function here reads `brentlab_yeast.duckdb` through a read-only connection; the
SQL that *builds* that file lives in `tfbpshiny/materialize/` and is documented in
[materialized_db_schema.md](materialized_db_schema.md).

Conventions:

- Table and column names are f-string interpolated (DuckDB cannot parameterize
  identifiers); values are bound as `?` positional parameters for `conn.execute`, or as
  `$name` parameters where the function returns `(sql, params)` for the caller to run.
- "Builder" functions return `(sql, params)` without executing. "Executes" functions run
  the query and return a `pandas.DataFrame` (or a plain Python object where stated).
- A `filters` argument is the per-dataset sample filter dict committed on the selection
  tab, already expanded so every variant carries its primary's filter
  (`app.py::analysis_filters` → `expand_filters_to_variants`).

---

## `select_datasets` module

**File:** `tfbpshiny/modules/select_datasets/queries.py`
**Called from:** `server/workspace.py`, `server/sidebar.py`, `server/dataset_row.py`

All seven public functions are **Builders** that read one dataset's `{db_name}_meta` table
(or the full data view) with an optional filter spec `{field: {"type": categorical |
numeric | bool, "value": ...}}`. Filter clauses are built once by `_build_filter_clauses`
and bound as `$cat_{field}_{i}`, `$num_{field}_lo/_hi`, `$bool_{field}`.

| Function | Purpose | Result |
|---|---|---|
| `metadata_query(db_name, filters)` | All sample-level metadata for one dataset, optionally filtered. | Every column of `{db_name}_meta`. |
| `sample_count_query(db_name, filters, restrict_to_regulators)` | Count samples passing the filter, optionally only for a regulator list. | one row: `n_samples`. |
| `regulator_locus_tags_query(db_name, filters)` | Distinct regulators among the samples passing the filter. | `regulator_locus_tag`, `regulator_symbol`. |
| `regulator_breakdown_query(db_name, candidate_cols, filters)` | One pass counting multi-sample regulators and distinct values per candidate condition column. | counts per column. |
| `regulator_conditions_query(db_name, locus_tag, candidate_cols, filters)` | `sample_id` plus the condition columns for every sample of one regulator (every sample is returned, with a flag for whether it passes the filter). | per-sample rows. |
| `regulator_display_labels_query(db_name)` | Distinct regulator locus tags and symbols, unfiltered, for labels. | `regulator_locus_tag`, `regulator_symbol`. |
| `full_data_query(db_name, filters)` | The dataset's full data view restricted to the filtered samples, for export. | Every column of the data view. |

---

## Shared sample-filter helpers

**File:** `tfbpshiny/utils/corr_query.py`

| Function | Kind | Purpose |
|---|---|---|
| `expand_filters_to_variants(conn, filters, registry=None)` | Executes (reads `dataset_registry` and the `_meta` catalog) | Copies each primary dataset's filter onto its promoter-set and peak-calling variants, keeping only the filter fields a variant's metadata actually has. The one place filters are widened; every analysis module receives the result. |
| `get_filtered_sample_ids(conn, db_name, filters)` | Executes | `CAST(sample_id AS VARCHAR)` of the rows of `{db_name}_meta` that pass `filters`. Every other query restricts to samples via this list. |
| `sample_filter_clause(conn, db_name, filters, column)` | Builder | `AND <column> IN (...)` for one dataset's filtered samples, or `AND FALSE` when none pass. |
| `per_dataset_sample_clause(conn, db_names, filters, db_column, sample_column)` | Builder | The same restriction for several datasets at once, each to its own filtered samples. |
| `sample_in_clause(column, ids)` | Builder | `AND <column> IN (...)` for an already-resolved sample list; no restriction when `ids` is `None`. |
| `fetch_corr_pairs(conn, pairs, filters, method, score_type, comparison_type)` | Executes | Pre-computed per-regulator correlations from `correlations` for a list of `(db_a, db_b)` pairs, both sides restricted to filtered samples. Returns `{(db_a, db_b): DataFrame}` with `regulator_locus_tag`, `correlation`, `n_shared_targets`. Used by the Binding and Perturbation tabs. |

---

## `comparison` module

**File:** `tfbpshiny/modules/comparison/queries.py`
**Called from:** the modules in `server/`

| Function | Kind | Purpose | Result |
|---|---|---|---|
| `build_binding_index(registry_df, promoter_set_labels=None, method_labels=None)` | pure | Index of `dataset_registry` rows: variant → primary, promoter set, method; `resolve(primary, promoter_set, method)` → `db_name`. | `BindingIndex` |
| `fetch_topn_results(conn, pairs, filters, top_n, preset, require_full_overlap=True)` | Executes | Rows of `topn_results` for each `(binding_db, perturbation_db)` pair at one cutoff and the `(effect, pvalue)` pair `preset` (a per-dataset threshold table) gives the perturbation dataset, restricted to filtered samples. With `require_full_overlap` only rows whose top-N list is complete after the tie rule (`n >= top_n`) are kept. | `topn_results` columns + `pair_key`, `binding_db`, `perturbation_db` |
| `fetch_dto_results(conn, pairs, filters, pr_ranking_column, pvalue_threshold)` | Executes | DTO-significant fraction per pair over the regulators shared by the two datasets' filtered samples (`sample_regulator`). | one row per pair: `n_significant`, `n_covered`, `n_intersect`, `percent_significant` |
| `fetch_dto_results_method_intersected(conn, cells, filters, ...)` | Executes | Same metric for the Compare Analysis Methods tab, where each `(promoter_enrichment_db, peak_calling_db, perturbation_db)` cell shares one 3-way regulator universe so the two methods are compared over the same TFs. | two rows per cell |
| `fetch_method_promoter_target_universe(conn)` | Executes | Size of the candidate target pool each assay's model panel was restricted to (`method_promoter_model_target_universe`). | `assay_primary`, `display_name`, `n_targets` |
| `fetch_method_promoter_model(conn, perturbation_db, top_n, preset_name)` | Executes | The stored coefficients and fit summary of the method × promoter-set OLS for one `(dataset, N, preset)`. | `(coefs, fit_summary)` |

---

## `figures` module

**File:** `tfbpshiny/modules/figures/queries.py`
**Called from:** the modules in `server/`

Registry and helpers:

| Function | Kind | Purpose |
|---|---|---|
| `dataset_labels(conn)` | Executes | `db_name` → `base_label` for every registry row (variants share their primary's label). |
| `resolve_promoter_variant(conn, primary, promoter_set_id, method_id)` | Executes | The `db_name` of one (assay, promoter set, method) cell, or `None`. |
| `regulator_intersection(conn, db_names)` | Executes | Regulators present in every listed dataset, from `sample_regulator`. The TF population every figure is drawn over. |
| `sort_regulators_by_symbol(tags, symbols)` | pure | Alphabetical order by gene symbol for the Featured TF selector. |
| `scoring_clause(pr_db, preset_name, alias)` | Builder | `AND effect_threshold = ? AND pvalue_threshold = ?` pinning one responsiveness definition; every `topn_results` read must include it. |
| `agreement_dataset_choices(conn, comparison_type)` | Executes | Selectable datasets for figure 6, labelled and ordered. |

Figure data (all **Execute**; `filters` restricts both the binding and the perturbation
side to filtered samples):

| Function | Figure | Result columns |
|---|---|---|
| `fetch_rank_response(conn, binding_dbs, pr_db, regulators, filters, preset_name)` | 1 | `binding_db`, `regulator_locus_tag`, `n`, `percent_responsive` (median across samples per `n`) |
| `fetch_topn_percent_responsive(conn, binding_dbs, pr_db, regulators, top_n, filters, preset_name)` | 2, 7, 9 | `binding_db`, `regulator_locus_tag`, `percent_responsive` |
| `fetch_authors_bound(conn, binding_dbs, pr_db, filters, preset_name)` | 3 | `binding_db`, `regulator_locus_tag`, `percent_responsive`, `n_bound` (the `top_n = 0` rows) |
| `fetch_dto_significance(conn, binding_dbs, pr_dbs, ...)` | 4 | per pair: `n_significant`, `n_covered`, `n_shared`, `fraction_significant` |
| `fetch_dto_significant_sets(conn, binding_dbs, pr_db, ...)` | 5 | `{binding_db: set of regulators}` |
| `fetch_dto_significance_for_universe(conn, binding_db, pr_db, universe, ...)` | 9 (bottom) | `{"n_significant", "n_covered"}` within an explicit regulator universe |
| `fetch_agreement(conn, comparison_type, db_names, filters)` | 6 | `pair`, `db_a`, `db_b`, `regulator_locus_tag`, `top_n`, `log2_enrichment` |
| `weighted_agreement(df, half_life)` (pure) | 6 | `pair`, `regulator_locus_tag`, `weighted_enrichment` |
| `fetch_shared_targets(conn, comparison_type, db_names, top_n, filters)` | 10 | `pair`, `regulator_locus_tag`, `n_shared` |
| `fetch_target_sets(conn, db_names, regulator, top_n, filters)` | 10 (Venn) | `{db_name: set of targets}` |

---

## Registry readers

**File:** `tfbpshiny/utils/vdb_init.py`

| Function | Purpose |
|---|---|
| `load_app_datasets(conn)` | Reads `dataset_column_metadata` into the condition / upstream column lists the selection tab builds its filter UI from. |
| `get_regulator_display_name(conn, locus_tags=None)` | Reads `regulator_display_names` (locus tag, symbol, display name). |
| `promoter_set_labels(conn)`, `binding_method_labels(conn)` | Display label of each promoter set and binding method. |
| `promoter_set_info(conn)` | Label, description, colour and reference of each promoter set. |
| `binding_method_colors(conn)` | Series colour of each binding method. |
| `dataset_colors(conn, data_type)` | Series colour of each experiment of one data type, keyed by `base_label`. |
| `peak_calling_notes(conn)` | How each assay's peak calls were made, keyed by its primary `db_name`. |
| `get_responsiveness_label(preset_name, p_db)` | Pure: human-readable text for a preset's thresholds on one dataset. |

---

## Reading the SQL directly

Every builder is importable and side-effect free, so a notebook can inspect a query with
`sql, params = metadata_query("rossi_500bp", filters)` and run it against a read-only
connection. For the materialize-side generators (`topn_pair_select_sql_v2`,
`agreement_pair_select_sql`, `target_sets_select_sql`, ...), see
`tfbpshiny/materialize/comparison/` and the schema document.
