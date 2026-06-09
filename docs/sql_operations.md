# SQL Operations Reference

Complete catalogue of every SQL operation executed by TFBPShiny. Each entry documents the
query's purpose, template, parameters, and result shape. The "Approximate result size" rows
are populated after running `notebooks/sql_audit.ipynb`.

---

## Conventions

- All table/view names are f-string interpolated — DuckDB cannot parameterize identifiers.
- Filter values use DuckDB `$name` syntax (named parameters).
- Functions that return `(sql, params)` without executing are marked **Builder** in the
  Invocation column; the caller passes the result to `vdb.query(sql, **params)`.
- Functions that call `vdb.query()` internally are marked **Executes**.
- `sql_only=True` flag: where supported, returns `(sql, params)` instead of executing.

---

## `select_datasets` module

**File:** `tfbpshiny/modules/select_datasets/queries.py`
**Called from:** `server/workspace.py`, `server/sidebar.py`, `server/dataset_row.py`

All nine functions in this file are **Builders** — they return `(sql, params)` and never
call `vdb.query()` themselves.

---

### `metadata_query`

**Invocation:** Builder  
**sql_only path:** N/A  
**Purpose:** Fetch all sample-level metadata for one dataset, optionally filtered.

```sql
SELECT * FROM {db_name}_meta
[WHERE {filter_clauses}]
```

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `cat_{field}` | list | Categorical filter: field must equal any value in list |
| `num_{field}_lo` / `_hi` | float | Numeric filter: BETWEEN lo AND hi |
| `bool_{field}` | bool | Boolean filter: field = value |

**Result columns:** All columns in `{db_name}_meta` (schema varies by dataset).  
**Approximate result size:** TBD

---

### `sample_count_query`

**Invocation:** Builder  
**sql_only path:** N/A  
**Purpose:** Count how many samples (rows) match the current filters, optionally restricted
to a specific set of regulators.

```sql
SELECT COUNT(sample_id) AS n FROM {db_name}_meta
[WHERE {filter_clauses}]
[AND regulator_locus_tag IN ($reg_{db_name}_0, $reg_{db_name}_1, ...)]
```

**Parameters:** Same filter params as `metadata_query`, plus optional `reg_{db_name}_{i}`
per regulator in `restrict_to_regulators`.

**Result columns:** `n` (int — single row).  
**Approximate result size:** Trivial (1 row × 1 col).

---

### `regulator_locus_tags_query`

**Invocation:** Builder  
**sql_only path:** N/A  
**Purpose:** Return the distinct set of regulator locus tags present in a dataset after
applying filters.

```sql
SELECT DISTINCT regulator_locus_tag FROM {db_name}_meta
[WHERE {filter_clauses}]
```

**Parameters:** Filter params as above.  
**Result columns:** `regulator_locus_tag`.  
**Approximate result size:** TBD

---

### `regulator_display_labels_query`

**Invocation:** Builder  
**sql_only path:** N/A  
**Purpose:** Fetch the (locus_tag, symbol) pairs for a dataset, used to populate the
Regulator selectize in the filter modal. No parameters — returns all regulators.

```sql
SELECT DISTINCT regulator_locus_tag, regulator_symbol
FROM {db_name}_meta
ORDER BY regulator_locus_tag
```

**Parameters:** None.  
**Result columns:** `regulator_locus_tag`, `regulator_symbol`.  
**Approximate result size:** TBD

---

### `regulator_breakdown_query`

**Invocation:** Builder  
**sql_only path:** N/A  
**Purpose:** Determine whether a dataset has multiple samples per regulator (i.e., whether
an experimental-condition column is needed to disambiguate samples). Returns a single
aggregated row.

```sql
WITH per_reg AS (
    SELECT regulator_locus_tag,
           COUNT(DISTINCT "{col_1}") AS "{col_1}",
           COUNT(DISTINCT "{col_2}") AS "{col_2}",
           ...
    FROM {db_name}_meta
    [WHERE {filter_clauses}]
    GROUP BY regulator_locus_tag
    HAVING COUNT(*) > 1
)
SELECT COUNT(*) AS n_multi,
       COUNT(*) FILTER (WHERE "{col_1}" > 1) AS "{col_1}",
       COUNT(*) FILTER (WHERE "{col_2}" > 1) AS "{col_2}",
       ...
FROM per_reg
```

**Parameters:** Filter params as above.  
**Result columns:** `n_multi` + one column per entry in `candidate_cols` (int counts).  
**Approximate result size:** Trivial (1 row).

---

### `matrix_diagonal_query`

**Invocation:** Builder  
**sql_only path:** N/A  
**Purpose:** Count distinct regulators and samples for every active dataset in one query.
Used to populate the diagonal cells of the dataset-selection matrix.

```sql
SELECT '{db_name}' AS db_name,
       COUNT(DISTINCT regulator_locus_tag) AS n_regulators,
       COUNT(DISTINCT sample_id) AS n_samples
FROM {db_name}_meta
[WHERE {filter_clauses}]

UNION ALL

SELECT '{db_name_2}' AS db_name, ...
...
```

**Parameters:** One set of filter params per dataset, namespaced with `diag_{db_name}_`.  
**Result columns:** `db_name`, `n_regulators`, `n_samples`.  
**Approximate result size:** One row per active dataset (typically 6–10 rows).

---

### `matrix_cross_dataset_query`

**Invocation:** Builder  
**sql_only path:** N/A  
**Purpose:** For every (db_a, db_b) pair: count regulators in common and the restricted
sample counts for each side. Used to populate the off-diagonal cells of the dataset matrix.

```sql
-- One subquery per pair, unioned:
SELECT * FROM (
  WITH common AS (
    SELECT regulator_locus_tag FROM {db_a}_meta [WHERE ...]
    INTERSECT
    SELECT regulator_locus_tag FROM {db_b}_meta [WHERE ...]
  )
  SELECT '{db_a}__{db_b}' AS pair_id,
         (SELECT COUNT(*) FROM common) AS n_common,
         (SELECT COUNT(DISTINCT sample_id)
            FROM {db_a}_meta [WHERE ...] AND regulator_locus_tag IN (SELECT ... FROM common)) AS samples_a,
         (SELECT COUNT(DISTINCT sample_id)
            FROM {db_b}_meta [WHERE ...] AND regulator_locus_tag IN (SELECT ... FROM common)) AS samples_b
)
UNION ALL
...
```

**Parameters:** Two sets of filter params per pair, with distinct prefixes (`cross_`, `cs_`).  
**Result columns:** `pair_id`, `n_common`, `samples_a`, `samples_b`.  
**Approximate result size:** One row per pair (N choose 2; typically 15 rows for 6 datasets).

---

### `regulator_intersection_query`

**Invocation:** Builder  
**sql_only path:** N/A  
**Purpose:** Return the sorted list of regulator locus tags shared by two specific datasets
after applying their respective filters (excluding any regulator_locus_tag filter). Used to
populate the Regulator selector in a cross-dataset filter modal.

```sql
SELECT regulator_locus_tag FROM {db_a}_meta [WHERE ...]
INTERSECT
SELECT regulator_locus_tag FROM {db_b}_meta [WHERE ...]
ORDER BY regulator_locus_tag
```

**Parameters:** Filter params for db_a (prefix `ri_{db_a}_`) and db_b (prefix `ri_{db_b}_`).  
**Result columns:** `regulator_locus_tag`.  
**Approximate result size:** TBD

---

### `full_data_query`

**Invocation:** Builder  
**sql_only path:** N/A  
**Purpose:** Fetch all columns from the full data view (measurement + metadata joined) for
one dataset, optionally filtered.

```sql
SELECT * FROM {db_name}
[WHERE {filter_clauses}]
```

**Parameters:** Filter params as for `metadata_query`.  
**Result columns:** All columns in `{db_name}` (schema varies by dataset).  
**Approximate result size:** TBD — potentially large (millions of rows for full datasets).

---

## `binding` module

**File:** `tfbpshiny/modules/binding/queries.py`
**Called from:** `server/workspace.py`

---

### `binding_data_query`

**Invocation:** Builder  
**sql_only path:** N/A  
**Purpose:** Fetch per-target binding measurements for one dataset and measurement column.
Used as a subquery source by `corr_pair_sql` and `regulator_scatter_sql`.

```sql
SELECT regulator_locus_tag, target_locus_tag, target_symbol, sample_id, {col}
FROM {db_name}
[WHERE {filter_clauses}]
```

**Parameters:** Filter params as above.  
**Result columns:** `regulator_locus_tag`, `target_locus_tag`, `target_symbol`, `sample_id`,
`{col}` (measurement column, e.g. `enrichment`, `poisson_pval`).  
**Approximate result size:** TBD

---

### `corr_pair_sql` (binding)

**Invocation:** Executes (or Builder when `sql_only=True`)  
**sql_only path:** Yes  
**Purpose:** Compute per-regulator Pearson or Spearman correlation between two binding
datasets. Returns one row per (regulator, sample_a, sample_b) combination.

**Pearson template:**

```sql
WITH
  a_raw AS (
    SELECT regulator_locus_tag, target_locus_tag, target_symbol, sample_id, {col_a}
    FROM {db_a} [WHERE ...]
  ),
  b_raw AS (
    SELECT regulator_locus_tag, target_locus_tag, target_symbol, sample_id, {col_b}
    FROM {db_b} [WHERE ...]
  )
SELECT
  '{db_a}'                              AS db_a,
  a_raw.sample_id                       AS db_a_id,
  '{db_b}'                              AS db_b,
  b_raw.sample_id                       AS db_b_id,
  a_raw.regulator_locus_tag,
  corr(a_raw.{col_a}, b_raw.{col_b})   AS correlation
FROM a_raw
INNER JOIN b_raw
  ON  a_raw.regulator_locus_tag = b_raw.regulator_locus_tag
 AND a_raw.target_locus_tag    = b_raw.target_locus_tag
WHERE a_raw.{col_a} IS NOT NULL AND b_raw.{col_b} IS NOT NULL
  AND NOT isinf(a_raw.{col_a}) AND NOT isinf(b_raw.{col_b})
  AND NOT isnan(a_raw.{col_a}) AND NOT isnan(b_raw.{col_b})
GROUP BY a_raw.regulator_locus_tag, a_raw.sample_id, b_raw.sample_id
HAVING COUNT(*) >= 3
```

**Spearman template:** Same structure, but with additional `ranked` CTE that applies
`RANK() OVER (PARTITION BY regulator, sample_a, sample_b ORDER BY ...)` before `corr()`.

**Parameters:** Filter params for both datasets (namespaced with `{prefix}a_` / `{prefix}b_`).  
**Result columns:** `db_a`, `db_a_id`, `db_b`, `db_b_id`, `regulator_locus_tag`, `correlation`.  
**Approximate result size:** TBD

---

### `corr_all_pairs_sql` (binding)

**Invocation:** Executes  
**sql_only path:** No  
**Purpose:** Compute correlations for all active binding dataset pairs in a single query.
Wraps one `corr_pair_sql` subquery per pair in a `UNION ALL`.

```sql
SELECT *, '{db_a}__{db_b}' AS pair_key FROM ( {corr_pair_sql for pair 0} )
UNION ALL
SELECT *, '{db_a}__{db_b}' AS pair_key FROM ( {corr_pair_sql for pair 1} )
...
```

**Parameters:** All per-pair parameters merged with pair-index prefix `p{i}_`.  
**Result columns:** `db_a`, `db_a_id`, `db_b`, `db_b_id`, `regulator_locus_tag`,
`correlation`, `pair_key`.  
**Approximate result size:** TBD

---

### `regulator_scatter_sql` (binding)

**Invocation:** Builder  
**sql_only path:** N/A  
**Purpose:** Fetch per-target values for a single regulator across two binding datasets,
suitable for rendering a scatter plot. Returns ranks for Spearman, raw values for Pearson.

**Pearson template:**

```sql
WITH a AS (SELECT ... FROM {db_a} WHERE regulator_locus_tag = $reg_a [AND ...]),
     b AS (SELECT ... FROM {db_b} WHERE regulator_locus_tag = $reg_b [AND ...])
SELECT a.target_locus_tag,
       COALESCE(a.target_symbol, a.target_locus_tag) AS target_symbol,
       a.{col_a} AS _val_a,
       b.{col_b} AS _val_b
FROM a JOIN b ON a.target_locus_tag = b.target_locus_tag
```

**Spearman template:** Same, but wraps in an additional CTE with `RANK() OVER (...)` for
both columns.

**Parameters:** Filter params (namespaced `rp{idx}a_` / `rp{idx}b_`) plus `rp{idx}reg_a` /
`rp{idx}reg_b` for the regulator locus tag.  
**Result columns:** `target_locus_tag`, `target_symbol`, `_val_a`, `_val_b`.  
**Approximate result size:** TBD (one row per shared target for one regulator, typically
hundreds of rows).

---

## `perturbation` module

**File:** `tfbpshiny/modules/perturbation/queries.py`
**Called from:** `server/workspace.py`

The perturbation module uses the same `_corr_pair_sql_impl` as binding. The only difference
is `perturbation_data_query` replaces `binding_data_query` as the subquery builder.

---

### `perturbation_data_query`

**Invocation:** Builder  
**sql_only path:** N/A  
**Purpose:** Fetch per-target perturbation measurements for one dataset and measurement
column. Identical structure to `binding_data_query`.

```sql
SELECT regulator_locus_tag, target_locus_tag, target_symbol, sample_id, {col}
FROM {db_name}
[WHERE {filter_clauses}]
```

**Parameters:** Filter params.  
**Result columns:** `regulator_locus_tag`, `target_locus_tag`, `target_symbol`, `sample_id`,
`{col}`.  
**Approximate result size:** TBD

---

### `corr_pair_sql` (perturbation)

**Invocation:** Executes (or Builder when `sql_only=True`)  
**sql_only path:** Yes  
**Purpose:** Per-regulator Pearson or Spearman correlation between two perturbation datasets.
Identical SQL structure to binding's `corr_pair_sql` — only the data source differs.

See binding `corr_pair_sql` for full template. Replace `{db_a}` / `{db_b}` with perturbation
dataset names (e.g. `kemmeren`, `hackett`).

**Result columns:** `db_a`, `db_a_id`, `db_b`, `db_b_id`, `regulator_locus_tag`, `correlation`.  
**Approximate result size:** TBD

---

### `corr_all_pairs_sql` (perturbation)

**Invocation:** Executes  
**sql_only path:** No  
**Purpose:** Correlations for all active perturbation dataset pairs in one UNION ALL query.
Same structure as binding's `corr_all_pairs_sql`.

**Result columns:** `db_a`, `db_a_id`, `db_b`, `db_b_id`, `regulator_locus_tag`,
`correlation`, `pair_key`.  
**Approximate result size:** TBD

---

### `regulator_scatter_sql` (perturbation)

**Invocation:** Builder  
**sql_only path:** N/A  
**Purpose:** Per-target values for a single regulator across two perturbation datasets.
Identical SQL structure to binding's `regulator_scatter_sql`.

**Result columns:** `target_locus_tag`, `target_symbol`, `_val_a`, `_val_b`.  
**Approximate result size:** TBD (one row per shared target for one regulator).

---

## `comparison` module

**File:** `tfbpshiny/modules/comparison/queries.py`
**Called from:** `server/workspace.py` (inside `_run_analysis` extended task)

---

### `fetch_dto_data`

**Invocation:** Executes (or Builder when `sql_only=True`)  
**sql_only path:** Yes  
**Purpose:** Fetch the full DTO (Dual Transcription Overlap) empirical p-value table,
filtering to valid samples for each binding source. No user-controlled parameters.

```sql
SELECT
    d.binding_id_source,
    d.perturbation_id_source,
    d.dto_empirical_pvalue,
    d.dto_fdr,
    d.binding_set_size,
    d.perturbation_set_size,
    CAST(d.binding_id_id   AS VARCHAR) AS binding_sample_id,
    CAST(d.perturbation_id_id AS VARCHAR) AS pert_sample_id,
    COALESCE(CAST(h.time AS VARCHAR), 'standard') AS time
FROM dto_expanded d
LEFT JOIN (SELECT DISTINCT sample_id, time FROM hackett_meta WHERE time = 45) h
    ON d.perturbation_id_source = 'hackett'
   AND CAST(d.perturbation_id_id AS VARCHAR) = CAST(h.sample_id AS VARCHAR)
LEFT JOIN (SELECT DISTINCT sample_id FROM callingcards) cc
    ON d.binding_id_source = 'callingcards'
   AND CAST(d.binding_id_id AS VARCHAR) = CAST(cc.sample_id AS VARCHAR)
LEFT JOIN (SELECT DISTINCT sample_id FROM harbison WHERE condition = 'YPD') harb
    ON d.binding_id_source = 'harbison'
   AND CAST(d.binding_id_id AS VARCHAR) = CAST(harb.sample_id AS VARCHAR)
WHERE
    d.pr_ranking_column = 'log2fc'
    AND (d.perturbation_id_source != 'hackett'      OR h.sample_id IS NOT NULL)
    AND (d.binding_id_source != 'callingcards'      OR cc.sample_id IS NOT NULL)
    AND (d.binding_id_source != 'harbison'          OR harb.sample_id IS NOT NULL)
```

**Parameters:** None.  
**Result columns:** `binding_id_source`, `perturbation_id_source`, `dto_empirical_pvalue`,
`dto_fdr`, `binding_set_size`, `perturbation_set_size`, `binding_sample_id`, `pert_sample_id`,
`time`.  
**Approximate result size:** TBD

---

### `topn_responsive_ratio`

**Invocation:** Executes (or Builder when `sql_only=True`)  
**sql_only path:** Yes  
**Purpose:** For one (binding, perturbation) pair: compute the intersection of targets
present in both datasets, rank only the shared targets per binding sample, keep the top N,
then compute the fraction that are responsive (meet effect and p-value thresholds).
Intersecting before ranking ensures top-N slots are not consumed by binding targets absent
from the perturbation data.

```sql
WITH binding AS (
    -- Harbison: MIN(pvalue) dedup across condition = 'YPD'
    -- Others: direct SELECT with optional filters and target blacklist
    SELECT
        CAST({binding_sample_col} AS VARCHAR) AS binding_sample_id,
        regulator_locus_tag,
        target_locus_tag,
        {rank_col}
    FROM {binding_view}
    [WHERE target_locus_tag NOT IN ($bl_bp{i}_0, ...) [AND {filter_clauses}]]
),
perturbation AS (
    SELECT
        CAST(p.sample_id AS VARCHAR) AS perturbation_sample_id,
        p.regulator_locus_tag,
        p.target_locus_tag,
        CASE WHEN ABS(p.{effect_col}) > $bp{i}_eff_thresh
              AND p.{pvalue_col} < $bp{i}_pval_thresh
        THEN 1 ELSE 0 END AS is_responsive
    FROM {perturbation_view} p
    [WHERE {filter_clauses}]
),
intersecting_targets AS (
    SELECT DISTINCT b.regulator_locus_tag, b.target_locus_tag
    FROM binding b
    INNER JOIN perturbation pert
        ON  b.regulator_locus_tag = pert.regulator_locus_tag
        AND b.target_locus_tag    = pert.target_locus_tag
),
binding_ranked AS (
    SELECT
        b.binding_sample_id,
        b.regulator_locus_tag,
        b.target_locus_tag,
        b.{rank_col},
        RANK() OVER (
            PARTITION BY b.binding_sample_id
            ORDER BY b.{rank_col} {ASC|DESC}
        ) AS rnk
    FROM binding b
    INNER JOIN intersecting_targets it
        ON  b.regulator_locus_tag = it.regulator_locus_tag
        AND b.target_locus_tag    = it.target_locus_tag
    WHERE b.regulator_locus_tag != b.target_locus_tag
),
top_n_binding AS (
    SELECT binding_sample_id, regulator_locus_tag, target_locus_tag
    FROM binding_ranked
    WHERE rnk <= $bp{i}_top_n
)
SELECT
    b.binding_sample_id,
    b.regulator_locus_tag,
    pert.perturbation_sample_id,
    COUNT(*)                                    AS n,
    SUM(pert.is_responsive)::INTEGER            AS n_responsive,
    SUM(pert.is_responsive)::DOUBLE / COUNT(*)  AS responsive_ratio
FROM top_n_binding b
JOIN perturbation pert
    ON  b.regulator_locus_tag = pert.regulator_locus_tag
   AND b.target_locus_tag    = pert.target_locus_tag
GROUP BY b.binding_sample_id, b.regulator_locus_tag, pert.perturbation_sample_id
```

**Per-dataset binding configuration:**

| Dataset | `rank_col` | `rank_asc` | `binding_sample_col` | Dedup CTE | Blacklist |
|---------|-----------|-----------|----------------------|-----------|---------|
| `callingcards` | `poisson_pval` | True | `sample_id` | No | `CC_TARGET_BLACKLIST` |
| `callingcards_mindel` | `poisson_pval` | True | `sample_id` | No | `CC_TARGET_BLACKLIST` |
| `harbison` | `pvalue` | True | `sample_id` | Yes (MIN dedup, `condition='YPD'`) | No |
| `chec_m2025` | `enrichment` | False | `sample_id` | No | No |
| `chec_m2025_mindel` | `enrichment` | False | `sample_id` | No | No |
| `chec_m2025_peaks` | `peak_score` | False | `sample_id` | No | No |
| `rossi` | `enrichment` | False | `sample_id` | No | No |
| `rossi_mindel` | `enrichment` | False | `sample_id` | No | No |
| `rossi_peaks` | `peak_score` | False | `sample_id` | No | No |

**Per-dataset responsiveness (default "Standard" preset):**

| Dataset | `effect_col` | `pvalue_col` | Default thresholds |
|---------|-------------|-------------|-------------------|
| `degron` | `log2FoldChange` | `pvalue` | effect > 0, pval < 0.05 |
| `hughes_overexpression` | `mean_norm_log2fc` | (none) | effect > 0 |
| `hughes_knockout` | `mean_norm_log2fc` | (none) | effect > 0 |
| `kemmeren` | `Madj` | `pval` | effect > 0, pval < 0.05 |
| `hackett` | `log2_shrunken_timecourses` | (none) | effect > 0 |
| `hu_reimand` | `effect` | `pval` | effect > 0, pval < 0.05 |

**Parameters:** See template above. `bp{i}_` prefix where `i` is the pair index in a batch.  
**Result columns:** `binding_sample_id`, `regulator_locus_tag`, `perturbation_sample_id`,
`n`, `n_responsive`, `responsive_ratio`.  
**Approximate result size:** TBD

---

### `topn_all_pairs_sql`

**Invocation:** Executes  
**sql_only path:** No  
**Purpose:** Compute `topn_responsive_ratio` for all (binding, perturbation) pairs in one
UNION ALL query. The main query run by the Comparison tab's Execute Analysis.

```sql
SELECT *, '{b_db}__{p_db}' AS pair_key FROM ( {topn_responsive_ratio for pair 0} )
UNION ALL
SELECT *, '{b_db}__{p_db}' AS pair_key FROM ( {topn_responsive_ratio for pair 1} )
...
```

**Parameters:** All per-pair parameters merged with pair-index prefix `bp{i}_`.  
**Result columns:** `binding_sample_id`, `regulator_locus_tag`, `perturbation_sample_id`,
`n`, `n_responsive`, `responsive_ratio`, `pair_key`.  
**Approximate result size:** TBD

---

## `utils` module

---

### `_build_regulator_display_names` (startup DDL)

**File:** `tfbpshiny/utils/vdb_init.py`  
**Invocation:** Executes via `vdb._conn.execute()` (DDL, not `vdb.query()`)  
**sql_only path:** No  
**Called from:** `initialize_data()` at app startup  
**Purpose:** Materialize a `regulator_display_names` DuckDB table from all registered
dataset meta views. Run once at startup; result persists for the session.

```sql
CREATE OR REPLACE TABLE regulator_display_names AS
SELECT
    regulator_locus_tag,
    FIRST(regulator_symbol) AS regulator_symbol,
    CASE
        WHEN FIRST(regulator_symbol) IS NOT NULL
             AND FIRST(regulator_symbol) != ''
             AND FIRST(regulator_symbol) != FIRST(regulator_locus_tag)
        THEN FIRST(regulator_symbol) || ' (' || regulator_locus_tag || ')'
        ELSE regulator_locus_tag
    END AS display_name
FROM (
    SELECT DISTINCT regulator_locus_tag, regulator_symbol FROM {db_1}_meta
    UNION ALL
    SELECT DISTINCT regulator_locus_tag, regulator_symbol FROM {db_2}_meta
    ...
) __all
GROUP BY regulator_locus_tag
ORDER BY regulator_locus_tag
```

**Parameters:** None (db names are f-string interpolated).  
**Result:** Creates `regulator_display_names` table with columns `regulator_locus_tag`,
`regulator_symbol`, `display_name`.  
**Approximate result size:** TBD (one row per unique regulator across all datasets).

---

### `get_regulator_display_name`

**File:** `tfbpshiny/utils/vdb_init.py`  
**Invocation:** Executes via `vdb._conn.execute()` directly  
**sql_only path:** No  
**Purpose:** Fetch display name entries from the pre-built lookup table. Used at module
startup to build the `{locus_tag: display_name}` dict for plot labels.

```sql
-- All regulators:
SELECT * FROM regulator_display_names

-- Filtered to specific tags:
SELECT * FROM regulator_display_names
WHERE regulator_locus_tag = ANY(?)
```

**Parameters:** Optional positional list `[locus_tags]` (DuckDB `?` syntax — not `$name`).  
**Result columns:** `regulator_locus_tag`, `regulator_symbol`, `display_name`.  
**Approximate result size:** TBD (same as `regulator_display_names` table).

---

### `fetch_sample_condition_map`

**File:** `tfbpshiny/utils/sample_conditions.py`  
**Invocation:** Executes  
**sql_only path:** No  
**Purpose:** Build a `{sample_id: condition_label}` map for one dataset by querying its
`_meta` view for the condition columns that disambiguate multi-sample regulators. Column
names are double-quoted; identifier safety is checked before query construction.

```sql
SELECT sample_id, "{cond_col_1}", "{cond_col_2}", ...
FROM {db_name}_meta
```

**Parameters:** None (all columns f-string interpolated).  
**Result columns:** `sample_id` + one column per entry in `cols`.  
**Post-processing:** Python iterates rows and calls `build_condition_label()` to produce
the string label.  
**Approximate result size:** TBD (one row per sample in the dataset).

---

## Parameter naming conventions

| Pattern | Origin | Example |
|---------|--------|---------|
| `$cat_{field}` | `select_datasets._build_where` categorical | `$cat_Experimental_condition` |
| `$num_{field}_lo/hi` | `select_datasets._build_where` numeric | `$num_time_lo` |
| `$bool_{field}` | `select_datasets._build_where` boolean | `$bool_del_passed_qc` |
| `$cat_{prefix}{field}_{i}` | `binding/comparison._build_where` categorical (IN-list) | `$cat_bp0_b_poisson_pval_0` |
| `$num_{prefix}{field}_lo/hi` | `binding/comparison._build_where` numeric | `$num_bp0_b_time_lo` |
| `$bl_{prefix}_{i}` | `comparison.topn_responsive_ratio` target blacklist | `$bl_bp0_0` |
| `${prefix}_top_n` | `comparison.topn_responsive_ratio` top-N cutoff | `$bp0_top_n` |
| `${prefix}_eff_thresh` / `_pval_thresh` | `comparison.topn_responsive_ratio` responsiveness | `$bp0_eff_thresh` |
| `$diag_{db_name}_{field}` | `select_datasets.matrix_diagonal_query` | `$diag_rossi_time_lo` |
| `$cross_{pair}_{db}_{field}` | `select_datasets.matrix_cross_dataset_query` intersect arm | |
| `$cs_{pair}_{db}_{field}` | `select_datasets.matrix_cross_dataset_query` sample count arm | |
| `$ri_{db}_{field}` | `select_datasets.regulator_intersection_query` | |
| `$p{i}a_/b_` | `binding/perturbation._corr_pair_sql_impl` param namespace | `$p0a_cat_time_0` |
| `$rp{idx}a_/b_` | `binding/perturbation.regulator_scatter_sql` | |
| `$rp{idx}reg_a/b` | `binding/perturbation.regulator_scatter_sql` regulator | |
