# Database Schema

## Overview

Rather than perform analysis type functions at the target level in the 
app, these types of analyses will now be carried out offline. The result
will be saved into a .duckdb file based database, and that is what will 
be used to provide data to the app.  

In addition to the comparison type analyses, eg topn, dto or correlations,
the file based database will also store sample level metadata (including 
conditions, etc) and provide some 

**Layers:**

| Layer | Tables | Description |
|-------|--------|-------------|
| Coordinating | `promoter_sets`, `binding_methods`, `dataset_registry`, `comparative_dataset_registry` | Registry + display metadata, written from the collection config's `tags` and `tfbpshiny` section (see `tfbpshiny/config.py`) |
| Metadata | `{db_name}_meta` (one per dataset) | Materialized verbatim from VirtualDB `_meta` views; schema is dataset-specific |
| Comparison — HF-sourced | `{analysis_name}` (one per configured comparative dataset) | Materialized verbatim from the raw HuggingFace Parquet; composite `source_sample` IDs preserved |
| Comparison — computed | `topn_results`, `correlations` | Pairwise analysis results computed at materialization time; same `source_sample` format |

**What is intentionally excluded:**

- Target-level measurement data (`{db_name}` views — `target_locus_tag`,
  `enrichment`, `log2FoldChange`, etc.). These remain in the HuggingFace
  Parquet files and are accessed at runtime only when needed.
- Field definition / alias / mapping tables from the previous design. That
  mapping is handled inside labretriever / VirtualDB and is not re-encoded here.

---

## Coordinating Layer

### `promoter_sets`

Reference table for genomic region definitions used by binding datasets.
Factored out of the previous `binding_datasets.promoter_set` column and the
hardcoded `PROMOTER_SET_MAP` in `comparison/queries.py`.

The descriptions come from the `genome_resources` block in
`brentlab_yeast_collection.yaml`.

```sql
CREATE TABLE promoter_sets (
    promoter_set_id  VARCHAR  PRIMARY KEY,  -- 'kang' | 'mindel' | '500bp' | 'intergenic' | 'peaks'
    display_name     VARCHAR  NOT NULL,
    description      VARCHAR
);
```

| promoter_set_id | display_name | description |
|---|---|---|
| `kang` | Kang | 700 bp upstream of each start codon, truncated when a feature lies within 700 bp of the ORF |
| `mindel` | Mindel | Start codon to ≥ 700 bp upstream of the TSS (Park 2014 / Pelechano 2013 / Policastro 2020); start codon used when no TSS is defined |
| `500bp` | 500 bp | Exactly 500 bp upstream of the start codon; no truncation or extension |
| `intergenic` | Intergenic | Full intergenic region upstream of the 5′ end of the feature; 1 410 of 6 040 features are divergently transcribed |
| `peaks` | Peaks | Regions as called by the original authors' peak-calling pipeline; not a fixed promoter window |

---

### `binding_methods`

Distinguishes how binding signal was quantified. Factored out of the display
labels in `SCORING_VARIANT_MAP` in `comparison/queries.py`.

```sql
CREATE TABLE binding_methods (
    binding_method_id  VARCHAR  PRIMARY KEY,  -- 'promoter_enrichment' | 'peak_calling'
    display_name       VARCHAR  NOT NULL
);
```

| binding_method_id | display_name |
|---|---|
| `promoter_enrichment` | Promoter Enrichment |
| `peak_calling` | Peak Calling |

`peak_calling` datasets score a target from peaks overlapping it; all others use
counts aggregated over a fixed promoter window.

The recalled, promoter-set-matched peak datasets (`rossi_peaks_*`, `chec_m2025_peaks_*`)
are **dense**: every promoter of the set is reported for every sample, and a promoter with
no qualifying peak has a NULL `nearest_score` / `median_score` / `max_score` (Rossi:
`n_peaks = 0`; ChEC-seq: fewer than two replicates with a peak, `n_replicates < 2`; test
`max_score IS NOT NULL`, not `n_peaks > 0`). They are ranked on `max_score`, and a NULL
ranks as a score of 0, below every real score. The Rossi score is MACS -log10(q);
the ChEC-seq score is HOMER's normalized tag count (the datacard calls it -log10(q), which
it is not), so the two scales are not comparable. The authors' own peak calls
(`rossi_peaks`, `chec_m2025_peaks`) are sparse and unaffected.

Peak-calling datasets come in two flavours, distinguished by `promoter_set_id`:

- **`promoter_set_id = 'peaks'`** — the original authors' peak annotations
- **`promoter_set_id = 'array'`** — Harbison's ChIP-chip microarray probes.
  Neither `peaks` nor `array` appears in `tfbpshiny.datasets.PROMOTER_SET_LEVELS`, so neither ever
  becomes a column in the promoter-definition grid: both are region definitions
  fixed by something other than a choice of upstream window.
  (`rossi_peaks`, `chec_m2025_peaks`). These have no fixed upstream window, so
  they are not comparable against a promoter-set column.
- **`promoter_set_id IN ('kang','mindel','500bp','intergenic')`** — peaks
  re-called from the raw data and intersected with that promoter definition
  (`rossi_peaks_*` via MACS, `chec_m2025_peaks_*` via HOMER). Each pairs 1:1
  with the promoter-enrichment dataset over the same window, which is what the
  Comparison module's "Compare Analysis Methods" tab tabulates.

---

### `dataset_registry`

One row per `db_name`. Consolidates the two former registry tables
(`binding_datasets`, `perturbation_datasets`) and the hardcoded Python
dictionaries (`BINDING_LABEL_MAP`, `PERTURBATION_LABEL_MAP`,
`BINDING_BASE_LABEL_MAP`, `PROMOTER_SET_MAP`, `PRIMARY_DATASETS`,
`DEFAULT_ACTIVE_DATASETS`, `PROMOTER_VARIANT_PAIRS`).

```sql
CREATE TABLE dataset_registry (
    db_name              VARCHAR  PRIMARY KEY,
    hf_repo              VARCHAR  NOT NULL,     -- e.g. 'BrentLab/callingcards'
    hf_config            VARCHAR  NOT NULL,     -- e.g. 'annotated_feature_reprocess_yiming_analysis'
    data_type            VARCHAR  NOT NULL,     -- 'binding' | 'perturbation'
    assay                VARCHAR,               -- 'CallingCards' | 'ChIP-chip' | 'ChIPexo' | 'ChEC-seq' | 'TFKO' | 'overexpression'
    display_name         VARCHAR,               -- full label, e.g. '2026 Calling Cards (Mindel)'
    base_label           VARCHAR,               -- label without promoter-set suffix, e.g. '2026 Calling Cards'
    is_primary           BOOLEAN  NOT NULL,     -- TRUE → shown in main dataset selector
    is_active_default    BOOLEAN  NOT NULL,     -- TRUE → toggle on at startup
    -- binding-only (NULL for perturbation datasets)
    primary_db_name      VARCHAR  REFERENCES dataset_registry(db_name),
    promoter_set_id      VARCHAR  REFERENCES promoter_sets(promoter_set_id),
    binding_method_id    VARCHAR  REFERENCES binding_methods(binding_method_id)
);
```

**`primary_db_name`** is NULL for canonical datasets; set for promoter-set or
method variants (e.g. `callingcards_mindel → callingcards`). Together with
`base_label`, `promoter_set_id` and `binding_method_id`, the
`(primary_db_name, promoter_set_id, binding_method_id)` triple uniquely
identifies every binding dataset. `build_binding_index` in
`modules/comparison/queries.py` reads exactly these columns, which is why the
Comparison module no longer hand-maintains parallel label dicts.

**Rows:**

| db_name | data_type | display_name | base_label | is_primary | is_active_default | primary_db_name | promoter_set_id | binding_method_id |
|---|---|---|---|---|---|---|---|---|
| `callingcards_500bp` | binding | 2026 Calling Cards | 2026 Calling Cards | TRUE | TRUE | NULL | 500bp | promoter_enrichment |
| `chec_m2025_500bp` | binding | 2025 ChEC-seq (Mahendrawada) | 2025 ChEC-seq | TRUE | TRUE | NULL | 500bp | promoter_enrichment |
| `harbison` | binding | 2004 ChIP-chip (Harbison) | 2004 ChIP-chip | TRUE | FALSE | NULL | array | promoter_enrichment |
| `rossi_500bp` | binding | 2021 ChIP-exo (Rossi) | 2021 ChIP-exo | TRUE | TRUE | NULL | 500bp | promoter_enrichment |
| `degron` | perturbation | 2025 Degron (Mahendrawada) | 2025 Degron | TRUE | TRUE | NULL | NULL | NULL |
| `hackett` | perturbation | 2020 Overexpression (Hackett) | 2020 Overexpression | TRUE | TRUE | NULL | NULL | NULL |
| `hu_reimand` | perturbation | 2007 TFKO (Hu) | 2007 TFKO | TRUE | FALSE | NULL | NULL | NULL |
| `hughes_knockout` | perturbation | 2006 Knockout (Hughes) | 2006 Knockout | TRUE | FALSE | NULL | NULL | NULL |
| `hughes_overexpression` | perturbation | 2006 Overexpression (Hughes) | 2006 Overexpression | TRUE | FALSE | NULL | NULL | NULL |
| `kemmeren` | perturbation | 2014 TFKO (Kemmeren) | 2014 TFKO | TRUE | TRUE | NULL | NULL | NULL |
| `callingcards_intergenic` | binding | 2026 Calling Cards (Intergenic) | 2026 Calling Cards | FALSE | FALSE | callingcards_500bp | intergenic | promoter_enrichment |
| `callingcards_kang` | binding | 2026 Calling Cards (Kang) | 2026 Calling Cards | FALSE | FALSE | callingcards_500bp | kang | promoter_enrichment |
| `callingcards_mindel` | binding | 2026 Calling Cards (Mindel) | 2026 Calling Cards | FALSE | FALSE | callingcards_500bp | mindel | promoter_enrichment |
| `chec_m2025` | binding | 2025 ChEC-seq (Mahendrawada, Kang) | 2025 ChEC-seq | FALSE | FALSE | chec_m2025_500bp | kang | promoter_enrichment |
| `chec_m2025_intergenic` | binding | 2025 ChEC-seq (Mahendrawada, Intergenic) | 2025 ChEC-seq | FALSE | FALSE | chec_m2025_500bp | intergenic | promoter_enrichment |
| `chec_m2025_mindel` | binding | 2025 ChEC-seq (Mahendrawada, Mindel) | 2025 ChEC-seq | FALSE | FALSE | chec_m2025_500bp | mindel | promoter_enrichment |
| `chec_m2025_peaks` | binding | 2025 ChEC-seq Peaks (Mahendrawada) | 2025 ChEC-seq | FALSE | FALSE | chec_m2025_500bp | peaks | peak_calling |
| `chec_m2025_peaks_500bp` | binding | 2025 ChEC-seq Peaks (HOMER, 500bp) | 2025 ChEC-seq | FALSE | FALSE | chec_m2025_500bp | 500bp | peak_calling |
| `chec_m2025_peaks_intergenic` | binding | 2025 ChEC-seq Peaks (HOMER, Intergenic) | 2025 ChEC-seq | FALSE | FALSE | chec_m2025_500bp | intergenic | peak_calling |
| `chec_m2025_peaks_kang` | binding | 2025 ChEC-seq Peaks (HOMER, Kang) | 2025 ChEC-seq | FALSE | FALSE | chec_m2025_500bp | kang | peak_calling |
| `chec_m2025_peaks_mindel` | binding | 2025 ChEC-seq Peaks (HOMER, Mindel) | 2025 ChEC-seq | FALSE | FALSE | chec_m2025_500bp | mindel | peak_calling |
| `rossi` | binding | 2021 ChIP-exo (Rossi, Kang) | 2021 ChIP-exo | FALSE | FALSE | rossi_500bp | kang | promoter_enrichment |
| `rossi_intergenic` | binding | 2021 ChIP-exo (Rossi, Intergenic) | 2021 ChIP-exo | FALSE | FALSE | rossi_500bp | intergenic | promoter_enrichment |
| `rossi_mindel` | binding | 2021 ChIP-exo (Rossi, Mindel) | 2021 ChIP-exo | FALSE | FALSE | rossi_500bp | mindel | promoter_enrichment |
| `rossi_peaks` | binding | 2021 ChIP-exo Peaks | 2021 ChIP-exo | FALSE | FALSE | rossi_500bp | peaks | peak_calling |
| `rossi_peaks_500bp` | binding | 2021 ChIP-exo Peaks (MACS, 500bp) | 2021 ChIP-exo | FALSE | FALSE | rossi_500bp | 500bp | peak_calling |
| `rossi_peaks_intergenic` | binding | 2021 ChIP-exo Peaks (MACS, Intergenic) | 2021 ChIP-exo | FALSE | FALSE | rossi_500bp | intergenic | peak_calling |
| `rossi_peaks_kang` | binding | 2021 ChIP-exo Peaks (MACS, Kang) | 2021 ChIP-exo | FALSE | FALSE | rossi_500bp | kang | peak_calling |
| `rossi_peaks_mindel` | binding | 2021 ChIP-exo Peaks (MACS, Mindel) | 2021 ChIP-exo | FALSE | FALSE | rossi_500bp | mindel | peak_calling |

### `comparative_dataset_registry`

One row per configured comparative analysis. Records provenance so the
materialization pipeline knows whether to copy data from a HuggingFace Parquet
or compute it locally. Both sources use the same `source_sample` composite ID
format, so the same queries work regardless of origin.

```sql
CREATE TABLE comparative_dataset_registry (
    analysis_name    VARCHAR  PRIMARY KEY,  -- table name, e.g. 'dto', 'topn_results', 'correlations'
    provenance       VARCHAR  NOT NULL,     -- 'hf_parquet' | 'computed'
    description      VARCHAR,
    -- hf_parquet only (NULL for computed analyses)
    hf_repo          VARCHAR,              -- e.g. 'BrentLab/yeast_comparative_analysis'
    hf_config        VARCHAR               -- e.g. 'dto'
);
```

| analysis_name | provenance | hf_repo | hf_config |
|---|---|---|---|
| `dto` | `hf_parquet` | `BrentLab/yeast_comparative_analysis` | `dto` |
| `topn_results` | `computed` | NULL | NULL |
| `correlations` | `computed` | NULL | NULL |

**Notes:**

- Additional HuggingFace comparative datasets declared in the VirtualDB config
  appear here automatically at materialization time.
- An analysis that currently lives in HuggingFace (e.g. `dto`) could be
  recalculated locally; changing `provenance` to `computed` signals that the
  stored table was produced locally rather than copied from Parquet.

---

### `schema_version`

One row stamped by every build. The app compares `version` with
`tfbpshiny.datasets.SCHEMA_VERSION` at startup; a database built at another version is
reported on every page and the figures refuse to draw from it.

```sql
CREATE TABLE schema_version (
    version   INTEGER   NOT NULL,   -- tfbpshiny.datasets.SCHEMA_VERSION at build time
    built_at  TIMESTAMP NOT NULL,
    git_sha   VARCHAR               -- commit the materializer ran from; NULL outside git
);
```

## Metadata Layer

Each registered dataset's VirtualDB `{db_name}_meta` view is materialized
verbatim as a DuckDB table. There is no unified schema across datasets; each
table's columns are determined by the dataset's HuggingFace datacard and the
field mappings in `brentlab_yeast_collection.yaml`.

**Universal columns** (present in every `_meta` table):

| Column | Description |
|---|---|
| `sample_id` | Primary key within the dataset |
| `regulator_locus_tag` | Systematic gene identifier |
| `regulator_symbol` | Gene name; absent for some datasets |

**Dataset-specific columns** (representative; verify against the actual
datacard for the authoritative list):

| Table | Notable columns |
|---|---|
| `callingcards_meta` | `total_background_hops`, `total_experiment_hops`, `carbon_source`, `temperature_celsius` |
| `harbison_meta` | `condition` (YPD, YP-galactose, …) |
| `rossi_meta` | `antibody`, `growth_media`, `treatment`, `carbon_source`, `temperature_celsius` |
| `chec_m2025_meta` | `condition`, `mahendrawada_symbol`, `carbon_source`, `temperature_celsius` |
| `hackett_meta` | `time`, `date`, `mechanism`, `restriction`, `strain` |
| `hu_reimand_meta` | `average_od_of_replicates`, `heat_shock`, `carbon_source`, `temperature_celsius` |
| `hughes_overexpression_meta` | `del_passed_qc`, `sgd_description`, `carbon_source`, `temperature_celsius` |
| `hughes_knockout_meta` | `oe_passed_qc`, `sgd_description`, `carbon_source`, `temperature_celsius` |
| `kemmeren_meta` | `carbon_source`, `temperature_celsius` |
| `degron_meta` | `env_condition`, `timepoint` |

**Notes:**

- Hidden filter fields (from `HIDDEN_FILTER_FIELDS` in `vdb_init.py`) are
  present in these tables but suppressed in the UI at runtime. They are not
  removed at materialization time.
- `FIELD_TYPE_OVERRIDES` in `vdb_init.py` governs how the UI interprets column
  types (e.g. treating `time` as categorical numeric). This remains
  application-level logic, not encoded in the schema.
- Promoter-set variants (`callingcards_mindel`, `rossi_500bp`, etc.) each have
  their own `_meta` table. Their metadata columns are identical to the primary
  dataset's; only the measurement data differs.

---

## Comparison Layer

All comparison tables follow the labretriever `comparative` dataset format (see
[`docs/huggingface_datacard.md`](../../labretriever/docs/huggingface_datacard.md)
in the labretriever reference). Each row is an observation involving two or
more samples, identified by `source_sample` composite strings in the format:

```
"hf_repo;hf_config;sample_id"
```

This is the same format used in the HuggingFace Parquet files stored in
`BrentLab/yeast_comparative_analysis`, so data from either source can be
queried identically.

**Joining any `source_sample` column back to `dataset_registry`:**

```sql
-- resolves the db_name for a source_sample column
(
    SELECT db_name
    FROM dataset_registry
    WHERE hf_repo   = split_part(<source_sample_col>, ';', 1)
      AND hf_config = split_part(<source_sample_col>, ';', 2)
)
```

VirtualDB also exposes `{analysis_name}_expanded` views that parse the
composite IDs into `{link_field}_source` (mapped to `db_name`) and
`{link_field}_id` (sample_id component). The materialized tables store the
raw composite strings; use `split_part` or join to `dataset_registry` at
query time to recover the parsed form.

---

## HuggingFace-Sourced Comparative Tables

One table per entry in `comparative_dataset_registry` with
`provenance = 'hf_parquet'`. Materialized verbatim from the raw HuggingFace
Parquet (not from the VirtualDB `_expanded` view), so the composite
`source_sample` identifiers are preserved exactly as stored upstream.

The schema for each table is dataset-specific. The authoritative definition
lives in the HuggingFace datacard for that repo. The sections below document
the currently configured datasets.

### `dto`

Direct target overlap (DTO) empirical p-values, pre-computed by the Brent Lab and
stored in `BrentLab/yeast_comparative_analysis;dto`.

Each row is a (binding sample, perturbation sample) pair for which a DTO score was
computed. Both sides of a row always refer to the **same regulator**.

```sql
CREATE TABLE dto (
    binding_source_sample       VARCHAR  NOT NULL,  -- 'hf_repo;hf_config;sample_id'
    perturbation_source_sample  VARCHAR  NOT NULL,  -- 'hf_repo;hf_config;sample_id'
    binding_db                  VARCHAR  NOT NULL,  -- resolved db_name
    binding_sample_id           VARCHAR  NOT NULL,
    perturbation_db             VARCHAR  NOT NULL,  -- resolved db_name
    perturbation_sample_id      VARCHAR  NOT NULL,
    regulator_locus_tag         VARCHAR,            -- resolved via sample_regulator
    pr_ranking_column           VARCHAR  NOT NULL,  -- 'log2fc' | 'pvalue'
    dto_empirical_pvalue        DOUBLE,
    dto_fdr                     DOUBLE,
    binding_set_size            DOUBLE,
    perturbation_set_size       DOUBLE,
    PRIMARY KEY (binding_source_sample, perturbation_source_sample, pr_ranking_column)
);
```

**Grain:** one row per `(binding_sample, perturbation_sample, pr_ranking_column)`.
A regulator contributes several rows per dataset pair when either side has multiple
samples for it — Hackett averages ~7.9 rows per regulator across timepoints, most
others ~1–2.

**Source view.** The rows come from VirtualDB's `dto_expanded` view, **not** a view
named `dto`. labretriever treats any dataset with a `links:` block as *comparative*
and deliberately registers only `__dto_parquet` plus `dto_expanded` for it. Reading
`dto_expanded` also resolves each composite identifier's `repo;config` prefix to our
own `db_name` using that `links:` block, which is why the block must list every
binding and perturbation dataset present in the DTO partitions (currently 22 and 6).

**Measured contents** (47,494 rows):

| | |
|---|---|
| `pr_ranking_column = 'log2fc'` | 36,003 rows |
| `pr_ranking_column = 'pvalue'` | 11,491 rows |
| `dto_empirical_pvalue` NULL | 0 |
| `dto_empirical_pvalue < 0.01` | 17,138 (36.1%) |
| distinct `binding_db` / `perturbation_db` | 22 / 6 |

**Notes:**

- Coverage of `pr_ranking_column` is uneven: Hackett and both Hughes sets exist only
  as `log2fc`; Kemmeren, Hu and Degron carry both at a 50/50 split. Comparisons
  across perturbation datasets should pin a single value.
- `harbison` has **no** DTO partitions, despite appearing in older versions of the
  `links:` block.
- DTO does not test every regulator shared by a dataset pair. For
  `rossi_peaks_kang` × `kemmeren` it covers 414 of the 446 shared regulators, so a
  denominator taken from `sample_regulator` is larger than DTO's own coverage.
- `dto_fdr` is **not bounded by 1** — 181 rows exceed it, max 3.41 — and is not
  monotonically consistent with the p-value column (`hughes_overexpression`: 29% of
  rows have p < 0.01 but only 10% have FDR < 0.05). Check
  `scripts/parse_dto_results.R` upstream before using it.

`sample_regulator` also backs the Figures page: every figure is drawn over an
intersection of regulator sets, which this table makes a single `INTERSECT` away.
Measured intersections, for reference:

| set | TFs |
|---|---|
| all four binding datasets | 70 |
| three binding datasets (no ChIP-chip) | 77 |
| all four binding ∩ kemmeren / hackett / degron | 69 / 61 / 61 |
| all four binding ∩ all three perturbation datasets | 54 |

Note ChIP-chip is absent from `dto` entirely, so the DTO figures are three binding
datasets wide rather than four.

### `topn_target_sets`

The actual ranked targets behind figure 10's Venn diagram and overlap boxes, per sample
and regulator, for the six datasets it uses (Calling Cards, Rossi and ChEC-seq at 500 bp;
Kemmeren, Hackett and Degron). `topn_agreement` keeps only overlap *counts* on a fixed
grid, which cannot draw a Venn and lacks the 25 and 75 the Figures sidebar offers.

```sql
CREATE TABLE topn_target_sets (
    source_sample       VARCHAR  NOT NULL,   -- repo;config;sample_id
    comparison_type     VARCHAR  NOT NULL,   -- 'binding' | 'perturbation'
    regulator_locus_tag VARCHAR  NOT NULL,
    target_locus_tag    VARCHAR  NOT NULL,
    rnk                 INTEGER  NOT NULL,   -- 1 = best; kept to 100
    -- plain identity columns beside the composite key, for readers
    db_name             VARCHAR  NOT NULL,   -- dataset db_name
    sample_id           VARCHAR  NOT NULL,
    PRIMARY KEY (source_sample, regulator_locus_tag, target_locus_tag)
);
```

"In the top N" is `rnk <= N` at read time, for any N up to 100. Ranking follows
`topn_agreement` (same rank columns and overrides, absolute effect for perturbation,
`target_locus_tag` tiebreak) except that duplicate rows for a target are collapsed first:
Kemmeren and Hackett measure some genes with several probes, which would otherwise count
one target twice and leave fewer than N distinct targets.

### `topn_agreement`

Per-regulator overlap between the top-N target sets of two datasets of the **same**
type -- binding vs. binding, or perturbation vs. perturbation.

```sql
CREATE TABLE topn_agreement (
    source_sample_a     VARCHAR  NOT NULL,
    source_sample_b     VARCHAR  NOT NULL,
    comparison_type     VARCHAR  NOT NULL,   -- 'binding' | 'perturbation'
    regulator_locus_tag VARCHAR  NOT NULL,
    top_n               INTEGER  NOT NULL,
    n_a                 INTEGER  NOT NULL,
    n_b                 INTEGER  NOT NULL,
    n_intersect         INTEGER  NOT NULL,
    -- plain identity columns beside the composite key, for readers
    db_a                VARCHAR  NOT NULL,
    sample_a            VARCHAR  NOT NULL,
    db_b                VARCHAR  NOT NULL,
    sample_b            VARCHAR  NOT NULL,
    PRIMARY KEY (source_sample_a, source_sample_b, regulator_locus_tag, top_n)
);
```

Only raw counts are stored; enrichment over chance is derived at read time as
`log2(n_intersect * 6000 / (n_a * n_b))`, so the gene-universe constant can be revisited
without a rebuild. The expectation uses the **observed** set sizes rather than `top_n^2`
— they diverge whenever a dataset has fewer than `top_n` targets for a regulator, which
is routine for peak calling, where the set size is whatever the caller returned.

Notes:

- Measured at ten log-spaced cutoffs to 500 (`AGREEMENT_TOP_N`). Agreement changes
  fastest at the top of the ranking, so a linear grid would waste points on the tail.
- Ranking uses `ROW_NUMBER()`, not the tie rule `topn_results` uses: sets must be exactly
  N so that figures 6 and 10 read as "shared out of N". `ROW_NUMBER()` alone is not
  reproducible when the ranking column ties, so `target_locus_tag` is appended as a final
  sort key to make the ordering total (the same targets fall inside the cutoff on every
  build).
- For the recalled peak datasets only **scored** rows are ranked (`drop_null_scores_*`).
  Ranking the NULL-score promoters too would pad a regulator that has fewer than N peaks
  up to exactly N with no-peak promoters in alphabetical order, and the overlaps would
  measure nothing.
- Ranking columns can be overridden per dataset for this table only, via
  `AGREEMENT_RANK_OVERRIDES` in `materialize/comparison/agreement.py`: Calling Cards
  ranks on `log_poisson_pval` and hackett on `log2_cleaned_ratio`. These do **not**
  affect `topn_results`, whose responsiveness calls stay on each dataset's published
  effect column. `n_a` / `n_b`
  still fall below `top_n` when a dataset simply has fewer targets for that regulator,
  which is why the read-time expectation uses them rather than `top_n`.
- **Every same-type dataset pair is materialized**, not only the primaries — figure 6's
  dataset selector compares promoter definitions and calling methods as well as assays,
  and which slice is interesting is a read-time question. 21 binding datasets give 210
  pairs. Excluded: `rossi_peaks` and `chec_m2025_peaks` (`AGREEMENT_EXCLUDED`), the
  authors' own peak calls, whose regions are not a fixed upstream window — a pair
  involving one differs in both the caller and the region.
- **Perturbation datasets are ranked by `ABS(effect)`**, so a knockout and an
  overexpression experiment are ordered by magnitude and can be compared.
- Restricted to *primary* datasets. The promoter-set and peak variants of one
  experiment agree with each other almost by construction, which would swamp the
  between-experiment comparison.
- Sanity check: a sample compared with itself gives `n_intersect = n_a = n_b`, and
  hence the theoretical maximum enrichment `log2(6000/N)` -- 7.91 at N = 25.

### `sample_regulator`

`(db_name, sample_id) -> regulator_locus_tag`, built from every `{db_name}_meta`
table that carries a regulator column.

```sql
CREATE TABLE sample_regulator (
    db_name             VARCHAR NOT NULL,
    sample_id           VARCHAR NOT NULL,
    regulator_locus_tag VARCHAR NOT NULL,
    PRIMARY KEY (db_name, sample_id)
);
```

`sample_id` is VARCHAR because the underlying meta tables disagree on type (VARCHAR
for callingcards and degron, INTEGER elsewhere) and DTO's composite identifiers are
strings. Two consumers:

1. populating `dto.regulator_locus_tag` — the DTO source ships no regulator column;
2. the DTO denominator, which counts regulators present in **both** a binding and a
   perturbation dataset.

---

## Locally Computed Comparison Tables

These tables are produced at `tfbpshiny materialize` time by executing the
queries in `comparison/queries.py` against the VirtualDB views. They use the
same `source_sample` composite ID format as the HuggingFace-sourced tables.

---

### `topn_results`

Top-N-by-binding responsive ratio for one (binding sample, perturbation
sample, regulator) triple. Computed by `topn_pair_select_sql` in
`materialize/comparison/topn.py`.

```sql
CREATE TABLE topn_results (
    binding_source_sample       VARCHAR  NOT NULL,  -- 'hf_repo;hf_config;sample_id'
    perturbation_source_sample  VARCHAR  NOT NULL,  -- 'hf_repo;hf_config;sample_id'
    regulator_locus_tag         VARCHAR  NOT NULL,
    top_n                       INTEGER  NOT NULL,   -- N used for ranking cutoff
    rank_col                    VARCHAR  NOT NULL,   -- column used to rank binding targets
    rank_asc                    BOOLEAN  NOT NULL,   -- TRUE → lowest value = rank 1 (p-values)
                                                     -- FALSE → highest = rank 1 (enrichment)
    effect_threshold            DOUBLE   NOT NULL,   -- |effect| > threshold → responsive
    pvalue_threshold            DOUBLE   NOT NULL,   -- padj/pval < threshold → responsive
    n                           INTEGER  NOT NULL,   -- targets in the top N present in both datasets
                                                      -- (tie rule: see Notes; can be < or > top_n)
    n_responsive                INTEGER  NOT NULL,
    responsive_ratio            DOUBLE   NOT NULL,   -- n_responsive / n
    n_intersecting_targets      INTEGER  NOT NULL,   -- distinct targets shared by this
                                                      -- sample pair for this regulator,
                                                      -- uncapped by top_n
    -- plain identity columns beside the composite key, for readers
    binding_db                  VARCHAR  NOT NULL,
    binding_sample_id           VARCHAR  NOT NULL,
    perturbation_db             VARCHAR  NOT NULL,
    perturbation_sample_id      VARCHAR  NOT NULL,
    PRIMARY KEY (
        binding_source_sample,
        perturbation_source_sample,
        regulator_locus_tag,
        top_n, rank_col, rank_asc,
        effect_threshold, pvalue_threshold
    )
);
```

**Grain:** one row per `(binding_sample, perturbation_sample, regulator,
analysis_config)`.

**Notes:**

- Self-interactions (regulator == target) are excluded by the query.
- The callingcards target blacklist (`YOR201C`, `YOR202W`, `YOR203W`,
  `YCL018W`, `YEL021W`) is applied at query time; it is a fixed constant in
  `comparison/queries.py` and is not a column here.
- Multiple rows can exist for the same sample pair and regulator when different
  `(top_n, rank_col, effect_threshold, pvalue_threshold)` combinations are
  pre-computed.
- **Ties: a tie group is in the top N only if its average rank is within N.** A group
  spanning ranks a..b has average rank (a+b)/2 (`RANK() + (group size - 1) / 2`). So a
  large tie group straddling the cutoff is excluded whole and leaves `n < top_n`, while a
  group kept whole can push `n` above `top_n` (a group of 2N-1 starting at rank 1 has
  average N). This replaced `RANK() <= N`, which kept the whole group whenever its first
  member was within N. (`topn_pair_select_sql*`'s `tie_rule` is `"avg_rank"`; `"rank"`
  reproduces the old behaviour exactly.) The ratio is taken over the `n` kept.
- **NULL scores rank as no signal.** For the recalled peak datasets
  (`BINDING_TOPN_CONFIGS[...]["no_signal_value"] = 0`) a NULL score is ranked as 0, so the
  no-peak promoters form one tie group at the bottom whose average rank is far above N
  unless the pool is tiny; a sample with few peaks therefore has a short list. Those
  promoters still count toward `n_intersecting_targets`.
- `n_intersecting_targets` is computed independently of the top-N cutoff, from
  the raw binding/perturbation overlap for that sample pair (blacklist/dedup
  applied, self-targets excluded). It is **not** filtered at materialize time
  (unlike `correlations.n_shared_targets`'s `HAVING COUNT(*) >= 3` floor,
  below) — it repeats identically across every `(top_n, rank_col,
  effect_threshold, pvalue_threshold)` row for the same sample pair and
  regulator. Because dense peak tables report every promoter it is large for every
  sample, so it no longer says whether a list is complete.
- **The Comparison module's "Require full overlap" toggle checks `n >= top_n`**: the list
  must still hold at least N targets after the tie rule. A regulator with too few scored
  targets, or a large tie group around rank N, is excluded when it is on.
- Built in three stages (`materialize/comparison/topn.py`): `binding_stage_sql` and
  `perturbation_stage_sql` materialize each source once, and `topn_pair_select_sql_v2`
  emits every `(top_n, effect_threshold, pvalue_threshold)` combination for a pair from
  one scan-and-rank. Ranking still happens *after* the intersecting-target restriction,
  so a target's rank depends on which perturbation dataset it is being compared against
  and cannot be shared between them.
- Defaults: `top_n ∈ {10, 25, 50, 75, 100}`, plus a `top_n = 0` sentinel for the
  peak datasets meaning "every authors'-bound target, no rank cutoff" (`n` then
  carries the size of the authors' bound set). Harbison (`pvalue <= 0.001`, YPD) and
  Calling Cards (Poisson p < 1e-4) have no binary call of their own, so their
  `top_n = 0` rows apply those named thresholds instead.
- **Responsiveness is decided by `(effect_threshold, pvalue_threshold)` and nothing
  else.** `tfbpshiny materialize` defaults to `--preset Relaxed --preset Stringent`,
  resolving each preset's pair *per perturbation dataset* from
  `DEFAULT_RESPONSIVENESS_PRESETS` in `utils/vdb_init.py`; `Stringent` holds each
  dataset's published criteria. So Kemmeren stores `(0.0, 0.05)` and `(0.77, 0.05)`
  while Degron stores `(0.0, 0.05)` and `(0.38, 0.1)`. **Every read must pin the
  pair** — a query that does not medians across both definitions of responsive.
- The `responsive` boolean shipped by some source parquets is deprecated upstream and
  is never read. A database whose `topn_results` still carries a `criteria` column
  predates this and holds rows scored from that flag; the app logs a warning at
  startup (`utils/schema_check.py`) because nothing filters them out any more.

---

---

### `correlations`

Pairwise Pearson or Spearman correlations between samples within the same
data type.

```sql
CREATE TABLE correlations (
    source_sample_a      VARCHAR  NOT NULL,  -- 'hf_repo;hf_config;sample_id'
    source_sample_b      VARCHAR  NOT NULL,  -- 'hf_repo;hf_config;sample_id'
    regulator_locus_tag  VARCHAR  NOT NULL,
    comparison_type      VARCHAR  NOT NULL,  -- 'binding' | 'perturbation'
    method               VARCHAR  NOT NULL,  -- 'pearson' | 'spearman'
    score_type           VARCHAR  NOT NULL,  -- 'effect' | 'pvalue' | 'log10pval'
    score_col_a          VARCHAR  NOT NULL,  -- raw column used from sample_a's dataset
    score_col_b          VARCHAR  NOT NULL,  -- raw column used from sample_b's dataset
    correlation          DOUBLE   NOT NULL,   -- rounded, see --float-decimals
    n_shared_targets     INTEGER  NOT NULL,  -- targets used; always >= 3
    -- plain identity columns beside the composite key, for readers
    db_a                 VARCHAR  NOT NULL,
    sample_a             VARCHAR  NOT NULL,
    db_b                 VARCHAR  NOT NULL,
    sample_b             VARCHAR  NOT NULL,
    PRIMARY KEY (
        source_sample_a, source_sample_b,
        regulator_locus_tag,
        method, score_type
    )
);
```

**Pair ordering:** `source_sample_a ≤ source_sample_b` (lexicographic) so each
unordered pair is stored exactly once.

**Notes:**

- `comparison_type` lets you filter to binding or perturbation rows without
  parsing sample IDs.
- `score_type` is computed for every dataset pair: `effect` always (every
  dataset has an effect column); `pvalue` and `log10pval` only when *both*
  sides of the pair have a non-empty pvalue column (`BINDING_DATASET_COLUMNS`
  / `PERTURBATION_DATASET_COLUMNS` in `materialize/comparison/correlations.py`
  — e.g. `hackett`, `hughes_overexpression`, `hughes_knockout` have none, so
  pairs involving them only get `effect` rows).
- `log10pval` is `-log10(GREATEST(pvalue, 1e-10))` — p-values below `1e-10`
  are floored so a single near-zero p-value can't blow up the scale.
- `score_col_*` records the raw column(s) actually used (e.g. `poisson_pval`
  for `pvalue`/`log10pval`, `callingcards_enrichment` for `effect`) for
  provenance/debugging; it is not part of the primary key since `score_type`
  plus the dataset pair already determines it deterministically.
- Rows are only written when `COUNT(shared targets) >= 3`.

---

### Method x promoter-set model

Two tables, populated by `materialize/comparison/method_promoter_model.py`. Answers the
relative contribution of the binding method (peak calling vs. promoter enrichment) and
of the 4 promoter definitions, holding regulator identity and assay constant --
a question the descriptive `topn_results`/`correlations` tables above cannot answer,
since they report medians rather than fit a model.

**Design:** a 16-cell panel (2 methods x 4 promoter sets x 2 assays -- Rossi ChIP-exo
and Mahendrawada ChEC-seq, the only two with both a promoter-enrichment and a
promoter-set-matched peak-calling arm) is fit with a pooled OLS:
`responsive_ratio ~ method + promoter_set + assay + C(regulator_locus_tag)`, with
cluster-robust standard errors by `regulator_locus_tag`. The regulator fixed effect
holds each TF's own baseline responsiveness constant while the method/promoter_set/
assay contrasts are estimated; the regulator dummy coefficients themselves are fit but
never stored in `_coefs`. Excluded structurally: Harbison (`promoter_set_id='array'`,
no re-quantifiable window), the authors' original peaks (`promoter_set_id='peaks'`, no
fixed window), and all `callingcards_*` (no peak-calling arm -- would unbalance the
method contrast). The panel is further restricted to (a) samples allowed by the app's
default per-dataset filters (`DEFAULT_DATASET_FILTERS`, e.g. Hackett's 45-minute
timepoint), matching every live Comparison query, and (b) regulators in the 3-way
intersection of the perturbation dataset's and both binding assays' regulator sets, so
the population is fixed across every cell. Fit once per
`(perturbation_db, top_n, criteria)`.

**Candidate pool and pairing.** Every cell is restricted to the targets shared by all
**eight** views of the assay (4 promoter sets x 2 methods; each is a complete list of its
set's targets), so a wider window cannot win by offering more candidates, and no view is
treated as the ground truth for another. Within each assay x promoter set a regulator is
kept only where **both methods have a row**: a regulator with no usable peak-calling list
is dropped, not scored as zero (earlier builds imputed such a regulator from the matching
promoter-enrichment row, which favoured promoter enrichment).

This is a **fixed-effects OLS, not a mixed model** -- a plain linear model, the
deliberately simple port of a full crossed-random-effects binomial GLMM design drafted
separately for an R-based analysis (`hf_yeast_explorer`), which explicitly ruled out
fitting that design in-app.

```sql
CREATE TABLE method_promoter_model_coefs (
    -- Only the Intercept, method, promoter_set (3 rows), and assay coefficients are
    -- kept -- the regulator fixed-effect dummies are fit (they make the model
    -- correct) but never displayed.
    perturbation_db  VARCHAR  NOT NULL,
    top_n            INTEGER  NOT NULL,
    criteria         VARCHAR  NOT NULL,
    term             VARCHAR  NOT NULL,  -- patsy term name
    estimate         DOUBLE,  -- percentage points
    std_error        DOUBLE,  -- percentage points
    t_value          DOUBLE,
    p_value          DOUBLE,
    PRIMARY KEY (perturbation_db, top_n, criteria, term)
);

CREATE TABLE method_promoter_model_fit_summary (
    -- One row per model fit. `note` explains a failed/degenerate fit (too few
    -- regulators, no variation in a factor) rather than leaving a silent blank.
    perturbation_db  VARCHAR  NOT NULL,
    top_n            INTEGER  NOT NULL,
    criteria         VARCHAR  NOT NULL,
    n_obs            INTEGER  NOT NULL,
    n_regulators     INTEGER  NOT NULL,
    r_squared        DOUBLE,
    converged        BOOLEAN  NOT NULL,
    note             VARCHAR,
    PRIMARY KEY (perturbation_db, top_n, criteria)
);
```

**Notes:**

- Reads `topn_results`, `dataset_registry`, and `{db}_meta` tables directly against the
  *output* connection -- no VirtualDB/HuggingFace hop, unlike the `dto` import above;
  every input is already local by the time this phase runs.
- `--skip-method-promoter-model` on `tfbpshiny materialize` skips this phase.
- The Comparison module's "Method × Promoter Model" tab only reads these tables; no
  fitting happens in the running app.

---

## Entity–Relationship Diagram

```
promoter_sets ──< dataset_registry >── binding_methods
                        │ (primary_db_name self-ref for variant rows)

{db_name}_meta tables — one per dataset, schema dataset-specific,
                         joined to dataset_registry via
                         hf_repo + hf_config → db_name at query time

comparative_dataset_registry — one row per analysis (hf_parquet or computed)

HuggingFace-sourced tables (provenance = 'hf_parquet'):
  dto.binding_id               ─┐
  dto.perturbation_id          ─┤→ dataset_registry (via split_part → hf_repo;hf_config)

Locally computed tables (provenance = 'computed'):
  topn_results.binding_source_sample       ─┐
  topn_results.perturbation_source_sample  ─┤→ dataset_registry (via split_part → hf_repo;hf_config)
  correlations.source_sample_a             ─┤
  correlations.source_sample_b             ─┘
```

---

## Materialization Parameters

| Option | Default | Description |
|--------|---------|-------------|
| `--config` | required | Path to VirtualDB YAML config |
| `--output` | `brentlab_yeast.duckdb` | Output `.duckdb` file path |
| `--methods` | `pearson,spearman` | Correlation methods to compute |
| `--top-n` | `10, 25, 50, 75, 100` | N for top-N analysis (repeatable) |
| `--effect-threshold` | `0.0` | Effect size threshold for responsiveness (repeatable) |
| `--pvalue-threshold` | `0.05` | Adjusted p-value threshold for responsiveness (repeatable) |
| `--skip-correlations` | false | Skip correlation computation |
| `--skip-topn` | false | Skip top-N computation |
| `--token` | env `HF_TOKEN` | HuggingFace token for private repos |

Repeatable options (`--top-n`, `--effect-threshold`, `--pvalue-threshold`) can
be supplied multiple times to pre-compute several analysis configurations in one
pass.

---

## Example Queries

### Which analyses are available and where they came from

```sql
SELECT analysis_name, provenance, hf_repo, hf_config
FROM comparative_dataset_registry
ORDER BY provenance, analysis_name;
```

### All primary binding datasets with their promoter set and method

```sql
SELECT
    dr.db_name,
    dr.display_name,
    ps.display_name  AS promoter_set,
    bm.display_name  AS binding_method
FROM dataset_registry dr
LEFT JOIN promoter_sets ps ON ps.promoter_set_id = dr.promoter_set_id
LEFT JOIN binding_methods bm ON bm.binding_method_id = dr.binding_method_id
WHERE dr.data_type = 'binding'
  AND dr.is_primary = TRUE
ORDER BY dr.base_label;
```

### All promoter-set variants of a primary binding dataset

```sql
SELECT db_name, display_name, promoter_set_id, binding_method_id
FROM dataset_registry
WHERE primary_db_name = 'callingcards_kang'
   OR db_name         = 'callingcards_kang'
ORDER BY promoter_set_id;
```

### Top-N results for callingcards → kemmeren, joined to display names

```sql
SELECT
    t.regulator_locus_tag,
    split_part(t.binding_source_sample,       ';', 3) AS binding_sample_id,
    split_part(t.perturbation_source_sample,  ';', 3) AS pert_sample_id,
    t.responsive_ratio,
    t.n,
    t.n_responsive,
    t.n_intersecting_targets
FROM topn_results t
WHERE t.binding_source_sample      LIKE 'BrentLab/callingcards;%'
  AND t.perturbation_source_sample LIKE 'BrentLab/kemmeren_2014;%'
  AND t.top_n              = 25
  AND t.rank_col           = 'poisson_pval'
  AND t.rank_asc           = TRUE
  AND t.effect_threshold   = 0.0
  AND t.pvalue_threshold   = 0.05
ORDER BY t.responsive_ratio DESC;
```

### Correlation matrix for a binding dataset pair, glucose only

```sql
SELECT
    c.source_sample_a,
    c.source_sample_b,
    c.regulator_locus_tag,
    c.correlation,
    c.n_shared_targets
FROM correlations c
WHERE c.source_sample_a   LIKE 'BrentLab/callingcards;%'
  AND c.source_sample_b   LIKE 'BrentLab/harbison_2004;%'
  AND c.comparison_type   = 'binding'
  AND c.method            = 'spearman'
  AND c.score_col_a       = 'callingcards_enrichment'
  AND c.score_col_b       = 'effect'
  -- filter binding sample to glucose via its _meta table
  AND split_part(c.source_sample_a, ';', 3) IN (
      SELECT CAST(sample_id AS VARCHAR)
      FROM callingcards_meta
      WHERE carbon_source = 'glucose'
  );
```

### DTO results for a specific binding × perturbation pair

```sql
-- callingcards (any sample) × kemmeren, log2fc ranking only
SELECT
    split_part(binding_id,       ';', 3) AS binding_sample_id,
    split_part(perturbation_id,  ';', 3) AS pert_sample_id,
    dto_empirical_pvalue,
    dto_fdr,
    binding_set_size,
    perturbation_set_size
FROM dto
WHERE binding_id      LIKE 'BrentLab/callingcards;%'
  AND perturbation_id LIKE 'BrentLab/kemmeren_2014;%'
  AND pr_ranking_column = 'log2fc'
ORDER BY dto_empirical_pvalue;
```

### Dataset metadata for a specific dataset (harbison)

```sql
SELECT *
FROM harbison_meta
LIMIT 10;
```

### All variants grouped by method for method-comparison tab

```sql
SELECT
    dr.base_label,
    dr.db_name,
    dr.display_name,
    bm.display_name  AS method,
    ps.display_name  AS promoter_set
FROM dataset_registry dr
LEFT JOIN binding_methods bm ON bm.binding_method_id = dr.binding_method_id
LEFT JOIN promoter_sets   ps ON ps.promoter_set_id   = dr.promoter_set_id
WHERE dr.data_type = 'binding'
  AND dr.primary_db_name IN ('rossi', 'chec_m2025')
ORDER BY dr.base_label, dr.binding_method_id, dr.promoter_set_id;
```
