# Database Schema

## Overview

The app reads a single DuckDB file, `brentlab_yeast.duckdb`, built offline by
`tfbpshiny materialize` from the collection config
(`tfbpshiny/brentlab_yeast_collection.yaml`) through `labretriever.VirtualDB`.
Every comparison the app shows (top-N responsiveness, DTO, correlations,
agreement, the method × promoter-set model) is computed or copied at build time;
the running app only reads and aggregates.

**Layers:**

| Layer | Tables | Description |
|-------|--------|-------------|
| Coordinating | `promoter_sets`, `binding_methods`, `dataset_registry`, `comparative_dataset_registry`, `dataset_column_metadata`, `schema_version` | Dataset identity and presentation (labels, colours, references, notes), from the collection config's `tags` and `tfbpshiny/datasets.py` |
| Metadata | `{db_name}_meta` (one per dataset), `sample_regulator`, `regulator_display_names` | Sample metadata copied from the VirtualDB `_meta` views, plus two lookups built from them |
| Comparison, copied | `dto` | Copied from the HuggingFace comparative dataset |
| Comparison, computed | `topn_results`, `topn_agreement`, `topn_target_sets`, `correlations`, `method_promoter_model_*` | Computed at build time |

Target-level measurement data (the `{db_name}` views: `target_locus_tag`,
`enrichment`, `log2FoldChange` and so on) is not stored. It stays in the
HuggingFace Parquet files and is read only during the build. Field definitions,
aliases and mappings stay in labretriever.

---

## Coordinating Layer

### `promoter_sets`

The genomic region definitions binding datasets are quantified over. Rows come
from `PROMOTER_SETS` in `tfbpshiny/datasets.py`. The description of each
promoter window is taken from the labretriever region set it names, declared in
the `genome_resources` block of the collection config.

```sql
CREATE TABLE promoter_sets (
    promoter_set_id  VARCHAR  PRIMARY KEY,
    display_name     VARCHAR  NOT NULL,
    description      VARCHAR,   -- from the labretriever region set it names
    color            VARCHAR,   -- series colour (figures 7/8)
    reference        VARCHAR    -- defining publication URL
);
```

| promoter_set_id | display_name | description |
|---|---|---|
| `kang` | Kang | 700 bp upstream of each start codon, truncated if there exists a feature within 700 bp of the ORF |
| `mindel` | Mindel | Start codon to at least 700 bp upstream of the TSS (Park 2014, Pelechano 2013, Policastro 2020); the start codon when no TSS is defined |
| `500bp` | 500bp | Exactly 500bp upstream of the start codon, with no truncation or extension |
| `intergenic` | Intergenic | The intergenic region upstream of the 5′ end of a feature; 1,410 of 6,040 features are divergently transcribed |
| `peaks` | Peaks | Regions as called by the original authors' peak-calling pipeline; not a fixed promoter window |
| `array` | Array Probes | Regions fixed by the ChIP-chip microarray platform; not re-quantifiable over a promoter window |

The first four are the comparable windows, `PROMOTER_SET_LEVELS` in
`tfbpshiny/datasets.py`, and the only promoter sets that appear as columns in
the Comparison page's promoter-definition and method tables. `peaks` and
`array` are fixed by something other than a choice of upstream window.

---

### `binding_methods`

How binding signal was quantified. Rows come from `BINDING_METHODS` in
`tfbpshiny/datasets.py`.

```sql
CREATE TABLE binding_methods (
    binding_method_id  VARCHAR  PRIMARY KEY,
    display_name       VARCHAR  NOT NULL,
    color              VARCHAR   -- series colour (figure 9, Comparison method rows)
);
```

| binding_method_id | display_name |
|---|---|
| `promoter_enrichment` | Promoter Enrichment |
| `peak_calling` | Peak Calling |

`peak_calling` datasets score a target from the peaks overlapping it; the others
use counts aggregated over a fixed promoter window. They come in two kinds,
distinguished by `promoter_set_id`:

- **`promoter_set_id = 'peaks'`**: the original authors' peak annotations
  (`rossi_peaks`, `chec_m2025_peaks`). These are sparse, and have no fixed
  upstream window.
- **`promoter_set_id` one of the four windows**: peaks re-called from the raw
  data and intersected with that promoter definition (`rossi_peaks_*` with MACS,
  `chec_m2025_peaks_*` with HOMER). Each pairs one-to-one with the
  promoter-enrichment dataset over the same window, which is what the
  Comparison page's "Compare Analysis Methods" tab tabulates.

The re-called peak datasets are **dense**: every promoter of the set is
reported for every sample. A promoter with no qualifying peak has a NULL
`nearest_score`, `median_score` and `max_score` (Rossi: `n_peaks = 0`; ChEC-seq:
fewer than two replicates with a peak, `n_replicates < 2`). Test
`max_score IS NOT NULL`, not `n_peaks > 0`. They are ranked on `max_score`, and
a NULL ranks as a score of 0, below every real score. The Rossi score is MACS
-log10(q). The ChEC-seq score is HOMER's normalized tag count (the datacard
calls it -log10(q), which it is not), so the two scales are not comparable.

---

### `dataset_registry`

One row per `db_name`. Every column comes from the collection config: the
HuggingFace repository and config from the dataset's location, and the rest from
its `tags`, where repository-level tags apply to every dataset in the repository
and dataset-level tags override them. `materialize` checks the tags before
writing (known promoter set and method, consistent primaries) and fails on an
inconsistency.

```sql
CREATE TABLE dataset_registry (
    db_name              VARCHAR  PRIMARY KEY,
    hf_repo              VARCHAR  NOT NULL,     -- e.g. 'BrentLab/callingcards'
    hf_config            VARCHAR  NOT NULL,
    data_type            VARCHAR  NOT NULL,     -- 'binding' | 'perturbation'
    assay                VARCHAR,               -- e.g. 'CallingCards', 'ChIPexo', 'RNA-seq'
    display_name         VARCHAR,               -- full label, e.g. '2026 Calling Cards (Mindel)'
    base_label           VARCHAR,               -- label without the variant suffix
    is_primary           BOOLEAN  NOT NULL,     -- TRUE: listed on the Dataset selection page
    is_active_default    BOOLEAN  NOT NULL,     -- TRUE: switched on at startup
    -- NULL for primaries; the primary this row is a variant of
    primary_db_name      VARCHAR  REFERENCES dataset_registry(db_name),
    -- binding only (NULL for perturbation datasets)
    promoter_set_id      VARCHAR  REFERENCES promoter_sets(promoter_set_id),
    binding_method_id    VARCHAR  REFERENCES binding_methods(binding_method_id),
    -- presentation, on primaries; variants share their primary's base_label
    color                VARCHAR,               -- series colour of the experiment
    peak_calling_note    VARCHAR,               -- how the assay's peak calls were made
    description          VARCHAR                -- dataset description (selection tooltip)
);
```

**`primary_db_name`** is NULL for a primary and names the primary for a
promoter-set or method variant (e.g. `callingcards_mindel` has
`callingcards_500bp`). `(primary_db_name, promoter_set_id, binding_method_id)`
identifies every binding variant; `build_binding_index` in
`modules/comparison/queries.py` reads exactly these columns.

**`description`** is labretriever's dataset description: the collection
config's `description` if it has one, else the HuggingFace DataCard's. The
Dataset selection page shows it as the tooltip of each dataset's name.

**Colours:** `callingcards_500bp`, `rossi_500bp`, `chec_m2025_500bp`, `harbison`,
`kemmeren`, `hackett` and `degron` carry a colour. **Peak-calling notes:**
`rossi_500bp` and `chec_m2025_500bp`, the two assays with re-called peaks.

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
| `hughes_knockout` | perturbation | 2006 TFKO (Hughes) | 2006 TFKO | TRUE | FALSE | NULL | NULL | NULL |
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

One row per comparison table, recording whether it was copied from a
HuggingFace Parquet file or computed during the build.

```sql
CREATE TABLE comparative_dataset_registry (
    analysis_name    VARCHAR  PRIMARY KEY,  -- table name
    provenance       VARCHAR  NOT NULL,     -- 'hf_parquet' | 'computed'
    description      VARCHAR,
    -- hf_parquet only (NULL for computed analyses)
    hf_repo          VARCHAR,
    hf_config        VARCHAR
);
```

| analysis_name | provenance | hf_repo | hf_config |
|---|---|---|---|
| `dto` | `hf_parquet` | `BrentLab/yeast_comparative_analysis` | `dto` |
| `topn_results` | `computed` | NULL | NULL |
| `correlations` | `computed` | NULL | NULL |

### `dataset_column_metadata`

The metadata columns the Dataset selection page offers as filters, one row per
`(db_name, column_name)`. `role` is `'condition'` for an experimental-condition
column with defined levels and `'upstream'` for any other filterable column.
Columns in `HIDDEN_FILTER_FIELDS` (`utils/vdb_init.py`) are left out.

```sql
CREATE TABLE dataset_column_metadata (
    db_name     VARCHAR NOT NULL,
    column_name VARCHAR NOT NULL,
    role        VARCHAR NOT NULL,   -- 'condition' | 'upstream'
    PRIMARY KEY (db_name, column_name)
);
```

### `schema_version`

One row stamped by every build. The app compares `version` with
`tfbpshiny.datasets.SCHEMA_VERSION` at startup; a database built at another
version is reported on every page and the figures refuse to draw from it.

```sql
CREATE TABLE schema_version (
    version   INTEGER   NOT NULL,   -- tfbpshiny.datasets.SCHEMA_VERSION at build time
    built_at  TIMESTAMP NOT NULL,
    git_sha   VARCHAR               -- commit the materializer ran from; NULL outside git
);
```

---

## Metadata Layer

### `{db_name}_meta`

Each registered dataset's VirtualDB `{db_name}_meta` view is copied verbatim as
a DuckDB table, one per dataset, 29 in all. There is no shared schema: each
table's columns come from the dataset's HuggingFace datacard and the field
mappings in the collection config. Every variant has its own table, with the
same columns as its primary's.

**Columns in every `_meta` table:**

| Column | Description |
|---|---|
| `sample_id` | Primary key within the dataset (VARCHAR or INTEGER, by dataset) |
| `regulator_locus_tag` | Systematic gene identifier |
| `regulator_symbol` | Gene name |

**Examples of dataset-specific columns** (the datacard is authoritative):

| Table | Notable columns |
|---|---|
| `rossi_500bp_meta` | `antibody`, `growth_media`, `multi_antibody`, `treatment` |
| `hackett_meta` | `time`, `date`, `mechanism`, `restriction`, `strain` |

Most tables also carry display-named condition columns such as
`Carbon source` and `Temperature`. Columns in `HIDDEN_FILTER_FIELDS` are kept
here and only hidden in the UI; `FIELD_TYPE_OVERRIDES` (`utils/vdb_init.py`)
governs how the UI treats a column's type.

### `sample_regulator`

`(db_name, sample_id) -> regulator_locus_tag`, built from every `_meta` table.

```sql
CREATE TABLE sample_regulator (
    db_name             VARCHAR NOT NULL,
    sample_id           VARCHAR NOT NULL,
    regulator_locus_tag VARCHAR NOT NULL,
    PRIMARY KEY (db_name, sample_id)
);
```

`sample_id` is VARCHAR because the `_meta` tables disagree on its type and the
DTO composite identifiers are strings. It is used to:

1. populate `dto.regulator_locus_tag`, since the DTO source has no regulator
   column;
2. count the regulators two datasets share (the DTO denominator);
3. intersect regulator sets for the Figures page. Measured intersections:

| set | regulators |
|---|---|
| the four binding primaries | 70 |
| the three 500bp binding primaries (no ChIP-chip) | 77 |
| the four binding primaries ∩ kemmeren / hackett / degron | 69 / 61 / 61 |
| the four binding primaries ∩ all three perturbation datasets | 54 |

### `regulator_display_names`

One display name per regulator, from the `regulator_symbol` values across every
`_meta` table.

```sql
CREATE TABLE regulator_display_names (
    regulator_locus_tag VARCHAR,
    regulator_symbol    VARCHAR,
    display_name        VARCHAR
);
```

---

## Comparison Layer

Every comparison row involves two samples. Each sample is identified two ways:

- a composite `source_sample` string, `hf_repo;hf_config;sample_id`, the
  labretriever comparative-dataset format, which is the primary key;
- plain identity columns beside it (`binding_db` / `binding_sample_id`, `db_a` /
  `sample_a`, and so on) holding the `db_name` and `sample_id`. Readers filter
  and join on these.

### `dto`

Dual threshold optimization
([DTO](https://github.com/BrentLab/dual_threshold_optimization)) empirical
p-values, computed by the Brent Lab and stored in
`BrentLab/yeast_comparative_analysis`, config `dto`. Each row is a (binding
sample, perturbation sample) pair for the **same regulator**.

```sql
CREATE TABLE dto (
    binding_source_sample       VARCHAR  NOT NULL,  -- 'hf_repo;hf_config;sample_id'
    perturbation_source_sample  VARCHAR  NOT NULL,
    binding_db                  VARCHAR  NOT NULL,
    binding_sample_id           VARCHAR  NOT NULL,
    perturbation_db             VARCHAR  NOT NULL,
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

**Grain:** one row per `(binding sample, perturbation sample,
pr_ranking_column)`. A regulator has several rows per dataset pair when either
side has several samples for it; Hackett averages about 7.9 rows per regulator
across timepoints, most others one or two.

**Source view.** The rows come from VirtualDB's `dto_expanded` view.
labretriever treats a dataset with a `links:` block as comparative and registers
only `__dto_parquet` and `dto_expanded` for it. `dto_expanded` resolves each
composite identifier's `repo;config` prefix to a `db_name` using that `links:`
block, so the block must list every binding and perturbation dataset present in
the DTO partitions.

**Measured contents** (51,968 rows):

| | |
|---|---|
| `pr_ranking_column = 'log2fc'` | 39,484 rows |
| `pr_ranking_column = 'pvalue'` | 12,484 rows |
| `dto_empirical_pvalue` NULL | 0 |
| `dto_empirical_pvalue < 0.01` | 18,563 (35.7%) |
| distinct `binding_db` / `perturbation_db` | 23 / 6 |

**Notes:**

- Coverage of `pr_ranking_column` is uneven: Hackett and both Hughes datasets
  exist only as `log2fc`; Kemmeren, Hu and Degron have both. A comparison
  across perturbation datasets should pin one value.
- `harbison` has no DTO partitions, so the DTO figures are three binding
  datasets wide rather than four.
- DTO does not test every regulator a dataset pair shares. For
  `rossi_peaks_kang` × `kemmeren` it covers 414 of 446 shared regulators, so a
  denominator taken from `sample_regulator` is larger than DTO's own coverage.
- `dto_fdr` is not bounded by 1 (239 rows exceed it, the largest 4.71) and is
  not consistent with the p-value column. Check `scripts/parse_dto_results.R`
  upstream before using it.

### `topn_results`

The fraction of a regulator's top-N bound targets that respond when it is
perturbed, for one (binding sample, perturbation sample, regulator) and one
analysis setting. Built by `materialize/comparison/topn.py`.

```sql
CREATE TABLE topn_results (
    binding_source_sample       VARCHAR  NOT NULL,  -- 'hf_repo;hf_config;sample_id'
    perturbation_source_sample  VARCHAR  NOT NULL,
    regulator_locus_tag         VARCHAR  NOT NULL,
    top_n                       INTEGER  NOT NULL,   -- rank cutoff; 0 = authors' bound set
    rank_col                    VARCHAR  NOT NULL,   -- column used to rank binding targets
    rank_asc                    BOOLEAN  NOT NULL,   -- TRUE: lowest value is rank 1 (p-values)
    effect_threshold            DOUBLE   NOT NULL,   -- |effect| > threshold: responsive
    pvalue_threshold            DOUBLE   NOT NULL,   -- p-value < threshold: responsive
    n                           INTEGER  NOT NULL,   -- targets in the top N present in both
                                                     -- datasets (can be < or > top_n)
    n_responsive                INTEGER  NOT NULL,
    responsive_ratio            DOUBLE   NOT NULL,   -- n_responsive / n
    n_intersecting_targets      INTEGER  NOT NULL,   -- targets the two samples share for
                                                     -- this regulator, not capped by top_n
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

**Notes:**

- Self-interactions (regulator equals target) are excluded.
- The Calling Cards target blacklist (`YOR201C`, `YOR202W`, `YOR203W`,
  `YCL018W`, `YEL021W`) is applied during the build; it is
  `CC_TARGET_BLACKLIST` in `materialize/comparison/topn.py`.
- **Ties: a tie group is in the top N only if its average rank is within N.**
  A group spanning ranks a..b has average rank (a+b)/2. A large tie group
  straddling the cutoff is excluded whole and leaves `n < top_n`, while a group
  kept whole can push `n` above `top_n` (a group of 2N-1 starting at rank 1 has
  average rank N). The ratio is taken over the `n` kept.
- **NULL scores rank as no signal.** For the re-called peak datasets
  (`BINDING_TOPN_CONFIGS[...]["no_signal_value"] = 0`) a NULL score ranks as 0,
  so the no-peak promoters form one tie group at the bottom and a sample with
  few peaks has a short list. Those promoters still count toward
  `n_intersecting_targets`.
- `n_intersecting_targets` comes from the raw binding/perturbation overlap for
  the sample pair (blacklist and deduplication applied, self-targets excluded)
  and repeats across every analysis setting for that pair and regulator. Dense
  peak tables report every promoter, so it is large for every peak sample and
  does not say whether a top-N list is complete.
- **The Comparison page's "Require full overlap" toggle checks `n >= top_n`.**
  A regulator with too few scored targets, or a large tie group around rank N,
  is excluded when it is on.
- Built in three stages: `binding_stage_sql` and `perturbation_stage_sql`
  materialize each source once, and `topn_pair_select_sql_v2` emits every
  `(top_n, effect_threshold, pvalue_threshold)` combination for a pair from one
  scan. Ranking happens after the restriction to intersecting targets, so a
  target's rank depends on the perturbation dataset it is compared against.
- **Cutoffs:** `top_n` is one of `TOP_N_CHOICES` (10, 25, 50, 75, 100), plus
  `top_n = 0` for `rossi_peaks`, `chec_m2025_peaks`, `harbison` and
  `callingcards_500bp`, meaning "every bound target, no rank cutoff" (`n` is
  then the size of the bound set). For the two peak datasets the bound set is
  the authors' own call; Harbison uses `pvalue <= 0.001` (YPD) and Calling
  Cards a Poisson p < 1e-4.
- **Responsiveness is decided by `(effect_threshold, pvalue_threshold)` and
  nothing else.** The build stores the pair each preset (`Relaxed`,
  `Stringent`) resolves to for each perturbation dataset, from
  `DEFAULT_RESPONSIVENESS_PRESETS` in `utils/vdb_init.py`; `Stringent` holds
  each dataset's published criteria. Kemmeren stores `(0.0, 0.05)` and
  `(0.77, 0.05)`; Degron stores `(0.0, 0.05)` and `(0.38, 0.1)`. **Every read
  must pin the pair**; a query that does not takes a median across both
  definitions of responsive.
- The `responsive` column some source parquets ship is never read.

### `topn_agreement`

Per-regulator overlap between the top-N target sets of two datasets of the
**same** type: binding vs. binding, or perturbation vs. perturbation. Built by
`materialize/comparison/agreement.py`.

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
    db_a                VARCHAR  NOT NULL,
    sample_a            VARCHAR  NOT NULL,
    db_b                VARCHAR  NOT NULL,
    sample_b            VARCHAR  NOT NULL,
    PRIMARY KEY (source_sample_a, source_sample_b, regulator_locus_tag, top_n)
);
```

Only counts are stored. Enrichment over chance is computed at read time as
`log2(n_intersect * 6000 / (n_a * n_b))` (`GENE_UNIVERSE` in
`tfbpshiny/datasets.py`), so the gene universe can be changed without a
rebuild. The expectation uses the observed set sizes rather than `top_n^2`;
they differ whenever a dataset has fewer than `top_n` targets for a regulator,
which is routine for peak calling.

**Notes:**

- Measured at 20 cutoffs, 10 to 200 in steps of 10 (`AGREEMENT_TOP_N`).
- Ranking uses `ROW_NUMBER()` with `target_locus_tag` as the final sort key,
  not the tie rule `topn_results` uses: sets are exactly N, so figures 6 and 10
  read as "shared out of N", and the same targets fall inside the cutoff on
  every build.
- For the re-called peak datasets only scored rows are ranked
  (`drop_null_scores_*`), so a regulator with fewer than N peaks is not padded
  with no-peak promoters.
- `AGREEMENT_RANK_OVERRIDES` sets the ranking column for this table only:
  Calling Cards ranks on `log_poisson_pval` and Hackett on
  `log2_cleaned_ratio`. These do not affect `topn_results`.
- Perturbation datasets are ranked by `ABS(effect)`, so a knockout and an
  overexpression experiment are ordered by magnitude and can be compared.
- **Every same-type dataset pair is stored**, variants included, because
  figure 6 lets the user compare promoter definitions and calling methods as
  well as assays. 21 binding datasets give 210 pairs. `rossi_peaks` and
  `chec_m2025_peaks` (`AGREEMENT_EXCLUDED`) are left out: their regions are not
  a fixed upstream window, so a pair involving one differs in both the caller
  and the region.
- Sanity check: a sample compared with itself gives `n_intersect = n_a = n_b`,
  and so the maximum enrichment `log2(6000/N)`, 7.91 at N = 25.

### `topn_target_sets`

The ranked targets behind figure 10's Venn diagram and overlap boxes, per
sample and regulator, for the datasets in `PROMOTER_ENRICHMENT_500BP` and
`HEADLINE_PERTURBATION`. `topn_agreement` keeps only overlap counts on a fixed
grid, which cannot draw a Venn diagram and lacks the 25 and 75 the Figures
sidebar offers.

```sql
CREATE TABLE topn_target_sets (
    source_sample       VARCHAR  NOT NULL,   -- 'hf_repo;hf_config;sample_id'
    comparison_type     VARCHAR  NOT NULL,   -- 'binding' | 'perturbation'
    regulator_locus_tag VARCHAR  NOT NULL,
    target_locus_tag    VARCHAR  NOT NULL,
    rnk                 INTEGER  NOT NULL,   -- 1 = best; kept to 100
    db_name             VARCHAR  NOT NULL,
    sample_id           VARCHAR  NOT NULL,
    PRIMARY KEY (source_sample, regulator_locus_tag, target_locus_tag)
);
```

"In the top N" is `rnk <= N`, for any N up to 100. Ranking follows
`topn_agreement` (same ranking columns and overrides, absolute effect for
perturbation, `target_locus_tag` tiebreak), except that duplicate rows for a
target are collapsed first: Kemmeren and Hackett measure some genes with
several probes, which would otherwise count one target twice.

### `correlations`

Per-regulator Pearson or Spearman correlation between two samples of the same
data type, over their shared targets. Built by
`materialize/comparison/correlations.py`.

```sql
CREATE TABLE correlations (
    source_sample_a      VARCHAR  NOT NULL,  -- 'hf_repo;hf_config;sample_id'
    source_sample_b      VARCHAR  NOT NULL,
    regulator_locus_tag  VARCHAR  NOT NULL,
    comparison_type      VARCHAR  NOT NULL,  -- 'binding' | 'perturbation'
    method               VARCHAR  NOT NULL,  -- 'pearson' | 'spearman'
    score_type           VARCHAR  NOT NULL,  -- 'effect' | 'pvalue' | 'log10pval'
    score_col_a          VARCHAR  NOT NULL,  -- column used from sample_a's dataset
    score_col_b          VARCHAR  NOT NULL,  -- column used from sample_b's dataset
    correlation          DOUBLE   NOT NULL,  -- rounded, see --float-decimals
    n_shared_targets     INTEGER  NOT NULL,  -- targets used; always >= 3
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

**Pair ordering:** `source_sample_a <= source_sample_b`, so each unordered pair
is stored once.

**Notes:**

- The score columns come from `BINDING_DATASET_COLUMNS` and
  `PERTURBATION_CORRELATION_COLUMNS` in `tfbpshiny/datasets.py`.
- `effect` is computed for every pair. `pvalue` and `log10pval` are computed
  only when both datasets have a p-value column; `hackett`,
  `hughes_overexpression` and `hughes_knockout` have none, so their pairs have
  only `effect` rows. `log10pval` is computed for Pearson only.
- `log10pval` is `-log10(GREATEST(pvalue, 1e-10))`, so a single near-zero
  p-value cannot dominate the scale.
- `score_col_*` records the column actually used (e.g. `poisson_pval` for
  `pvalue`, `callingcards_enrichment` for `effect`). It is not part of the key,
  since `score_type` and the dataset pair determine it.
- A row is written only when the two samples share at least 3 targets.

### Method × promoter-set model

Four tables, built by `materialize/comparison/method_promoter_model.py`. They
estimate how much the binding method (peak calling vs. promoter enrichment) and
the promoter definition each affect the percent of top-N targets that respond,
holding regulator and assay constant.

**Design.** A 16-cell panel (2 methods × 4 promoter sets × 2 assays, Rossi
ChIP-exo and Mahendrawada ChEC-seq, `METHOD_COMPARISON_ASSAYS`) is fitted with a
pooled OLS, `responsive_ratio ~ method + promoter_set + assay +
C(regulator_locus_tag)`, with standard errors clustered by regulator. The
regulator fixed effect holds each regulator's baseline responsiveness constant;
its coefficients are fitted but not stored. Harbison (`array`), the authors'
peaks (`peaks`) and Calling Cards (no peak-calling arm) are not in the panel.
The panel is restricted to:

- samples allowed by `DEFAULT_DATASET_FILTERS` (e.g. Hackett's 45-minute
  timepoint), the same default filters every Comparison query applies;
- regulators present in the perturbation dataset and both assays, so every cell
  covers the same regulators.

One model is fitted per `(perturbation_db, top_n, criteria)`, where `criteria`
is the preset name.

**Candidate pool and pairing.** Every cell ranks only the targets shared by all
eight views of its assay (4 promoter sets × 2 methods), so a wider window
cannot win by offering more candidates. Within each assay and promoter set a
regulator is kept only where both methods have a row; a regulator with no
usable peak-calling list is left out, not scored as zero.

This is a fixed-effects linear model, not a mixed model.

```sql
CREATE TABLE method_promoter_model_topn (
    -- same columns as topn_results, for the 16 panel cells, with each cell ranked
    -- over its assay's shared-target universe
    ...
);

CREATE TABLE method_promoter_model_target_universe (
    assay_primary  VARCHAR,   -- 'rossi_500bp' | 'chec_m2025_500bp'
    n_targets      INTEGER    -- size of the assay's shared-target universe
);

CREATE TABLE method_promoter_model_coefs (
    -- Intercept, method, promoter_set (3 rows) and assay terms only
    perturbation_db  VARCHAR  NOT NULL,
    top_n            INTEGER  NOT NULL,
    criteria         VARCHAR  NOT NULL,  -- 'Relaxed' | 'Stringent'
    term             VARCHAR  NOT NULL,  -- patsy term name
    estimate         DOUBLE,             -- percentage points
    std_error        DOUBLE,             -- percentage points
    t_value          DOUBLE,
    p_value          DOUBLE,
    PRIMARY KEY (perturbation_db, top_n, criteria, term)
);

CREATE TABLE method_promoter_model_fit_summary (
    -- one row per fit; `note` explains a failed or degenerate fit
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

- The fit reads `method_promoter_model_topn`, `dataset_registry` and the
  `_meta` tables from the output database.
- `--skip-method-promoter-model` skips these four tables.
- The Comparison page's "Method × Promoter Model" tab only reads them.

---

## Entity–Relationship Diagram

```text
promoter_sets ──< dataset_registry >── binding_methods
                        │ (primary_db_name: self-reference for variants)
                        │
                        ├── {db_name}_meta, sample_regulator,
                        │   dataset_column_metadata          (by db_name)
                        │
                        └── dto.binding_db / perturbation_db
                            topn_results.binding_db / perturbation_db
                            method_promoter_model_topn.binding_db / perturbation_db
                            topn_agreement.db_a / db_b
                            correlations.db_a / db_b
                            topn_target_sets.db_name          (by db_name)

comparative_dataset_registry: one row per comparison table
```

---

## Materialization Parameters

| Option | Default | Description |
|--------|---------|-------------|
| `--config` | required | Path to the collection config YAML |
| `--output` | `brentlab_yeast.duckdb` | Output `.duckdb` file path |
| `--methods` | `pearson,spearman` | Correlation methods to compute |
| `--top-n` | `10, 25, 50, 75, 100` | Rank cutoffs for `topn_results` (repeatable) |
| `--preset` | `Relaxed`, `Stringent` | Responsiveness presets whose per-dataset thresholds to store (repeatable) |
| `--effect-threshold` | `0.0` | Extra effect threshold applied to every dataset (repeatable) |
| `--pvalue-threshold` | `0.05` | Extra p-value threshold applied to every dataset (repeatable) |
| `--float-decimals` | `9` | Decimal places kept for computed floats; `-1` stores raw values |
| `--skip-correlations` | false | Skip `correlations` |
| `--skip-topn` | false | Skip `topn_results` |
| `--skip-method-promoter-model` | false | Skip the method × promoter-set tables |
| `--token` | env `HF_TOKEN` | HuggingFace token for private repos |

---

## Example Queries

### Primary binding datasets with their promoter set and method

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
  AND dr.is_primary
ORDER BY dr.base_label;
```

### Every variant of a primary binding dataset

```sql
SELECT db_name, display_name, promoter_set_id, binding_method_id
FROM dataset_registry
WHERE primary_db_name = 'callingcards_500bp'
   OR db_name         = 'callingcards_500bp'
ORDER BY promoter_set_id;
```

### Top-N results for Calling Cards × Kemmeren, Relaxed preset

```sql
SELECT
    regulator_locus_tag,
    binding_sample_id,
    perturbation_sample_id,
    responsive_ratio,
    n,
    n_responsive
FROM topn_results
WHERE binding_db       = 'callingcards_500bp'
  AND perturbation_db  = 'kemmeren'
  AND top_n            = 25
  AND effect_threshold = 0.0
  AND pvalue_threshold = 0.05
ORDER BY responsive_ratio DESC;
```

### Binding correlations for one pair, galactose samples only

```sql
SELECT c.sample_a, c.sample_b, c.regulator_locus_tag, c.correlation
FROM correlations c
WHERE c.db_a = 'callingcards_500bp'
  AND c.db_b = 'rossi_500bp'
  AND c.method     = 'spearman'
  AND c.score_type = 'pvalue'
  AND c.sample_a IN (
      SELECT CAST(sample_id AS VARCHAR)
      FROM callingcards_500bp_meta
      WHERE "Carbon source" = 'galactose'
  );
```

### DTO results for one binding × perturbation pair

```sql
SELECT
    regulator_locus_tag,
    binding_sample_id,
    perturbation_sample_id,
    dto_empirical_pvalue
FROM dto
WHERE binding_db        = 'rossi_500bp'
  AND perturbation_db   = 'kemmeren'
  AND pr_ranking_column = 'log2fc'
ORDER BY dto_empirical_pvalue;
```

### The datasets the method comparison covers

```sql
SELECT
    dr.base_label,
    dr.db_name,
    bm.display_name  AS method,
    ps.display_name  AS promoter_set
FROM dataset_registry dr
JOIN binding_methods bm ON bm.binding_method_id = dr.binding_method_id
JOIN promoter_sets   ps ON ps.promoter_set_id   = dr.promoter_set_id
WHERE dr.primary_db_name IN ('rossi_500bp', 'chec_m2025_500bp')
   OR dr.db_name         IN ('rossi_500bp', 'chec_m2025_500bp')
ORDER BY dr.base_label, dr.binding_method_id, dr.promoter_set_id;
```
