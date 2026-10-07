"""
SQL generators for the coordinating layer of the materialized DuckDB schema.

All functions return pure SQL strings (no side effects) so they can be called
from a Jupyter notebook to inspect output before running the full pipeline.
The coordinator is the only code that calls ``.execute()``.

"""

from __future__ import annotations

from labretriever import VirtualDB

from tfbpshiny.utils.vdb_init import HIDDEN_FILTER_FIELDS

# ---------------------------------------------------------------------------
# Mapping: db_name → (hf_repo, hf_config)
# Derived from brentlab_yeast_collection.yaml.
# ---------------------------------------------------------------------------

DATASET_HF_COORDS: dict[str, tuple[str, str]] = {
    "callingcards_kang": (
        "BrentLab/callingcards",
        "annotated_feature_reprocess_yiming_analysis",
    ),
    "callingcards_mindel": (
        "BrentLab/callingcards",
        "annotated_feature_reprocess_mindel_analysis",
    ),
    "callingcards_500bp": (
        "BrentLab/callingcards",
        "annotated_feature_reprocess_start_codon_500bp_analysis",
    ),
    "callingcards_intergenic": (
        "BrentLab/callingcards",
        "annotated_feature_reprocess_intergenic_analysis",
    ),
    "harbison": ("BrentLab/harbison_2004", "harbison_2004"),
    "rossi": ("BrentLab/rossi_2021", "rossi_2021_af_combined"),
    "rossi_mindel": ("BrentLab/rossi_2021", "rossi_2021_af_combined_mindel"),
    "rossi_500bp": ("BrentLab/rossi_2021", "rossi_2021_af_combined_start_codon_500bp"),
    "rossi_intergenic": ("BrentLab/rossi_2021", "rossi_2021_af_combined_intergenic"),
    "rossi_peaks": ("BrentLab/rossi_2021", "yep_filtered_peaks_combined"),
    "rossi_peaks_kang": ("BrentLab/rossi_2021", "macs_kang"),
    "rossi_peaks_mindel": ("BrentLab/rossi_2021", "macs_mindel"),
    "rossi_peaks_500bp": ("BrentLab/rossi_2021", "macs_bp500"),
    "rossi_peaks_intergenic": ("BrentLab/rossi_2021", "macs_intergenic"),
    "chec_m2025": (
        "BrentLab/mahendrawada_2025",
        "chec_mahendrawada_m2025_af_combined",
    ),
    "chec_m2025_mindel": (
        "BrentLab/mahendrawada_2025",
        "chec_mahendrawada_m2025_af_combined_mindel",
    ),
    "chec_m2025_500bp": (
        "BrentLab/mahendrawada_2025",
        "chec_mahendrawada_m2025_af_combined_start_codon_500bp",
    ),
    "chec_m2025_intergenic": (
        "BrentLab/mahendrawada_2025",
        "chec_mahendrawada_m2025_af_combined_intergenic",
    ),
    "chec_m2025_peaks": ("BrentLab/mahendrawada_2025", "mahendrawada_chec_seq"),
    "chec_m2025_peaks_kang": ("BrentLab/mahendrawada_2025", "kang_peaks"),
    "chec_m2025_peaks_mindel": ("BrentLab/mahendrawada_2025", "mindel_peaks"),
    "chec_m2025_peaks_500bp": ("BrentLab/mahendrawada_2025", "bp500_peaks"),
    "chec_m2025_peaks_intergenic": (
        "BrentLab/mahendrawada_2025",
        "intergenic_peaks",
    ),
    "kemmeren": ("BrentLab/kemmeren_2014", "kemmeren_2014"),
    "degron": ("BrentLab/mahendrawada_2025", "rnaseq_reprocessed"),
    "hackett": ("BrentLab/hackett_2020", "hackett_2020_analysis_set"),
    "hu_reimand": ("BrentLab/hu_2007_reimand_2010", "hu_2007_reimand_2010"),
    "hughes_overexpression": ("BrentLab/hughes_2006", "overexpression"),
    "hughes_knockout": ("BrentLab/hughes_2006", "knockout"),
}


def promoter_sets_sql() -> str:
    """
    Return SQL to create and populate the ``promoter_sets`` table.

    :returns: ``CREATE TABLE`` + ``INSERT`` SQL string.
    :rtype: str

    """
    return """
CREATE TABLE promoter_sets (
    promoter_set_id  VARCHAR  PRIMARY KEY,
    display_name     VARCHAR  NOT NULL,
    description      VARCHAR
);

INSERT INTO promoter_sets VALUES
    ('kang',
     'Kang',
     '700 bp upstream of each start codon, truncated when a feature lies within '
     || '700 bp of the ORF'),
    ('mindel',
     'Mindel',
     'Start codon to >= 700 bp upstream of the TSS (Park 2014 / Pelechano 2013 / '
     || 'Policastro 2020); start codon used when no TSS is defined'),
    ('500bp',
     '500 bp',
     'Exactly 500 bp upstream of the start codon; no truncation or extension'),
    ('intergenic',
     'Intergenic',
     'Full intergenic region upstream of the 5'' end of the feature; 1 410 '
     || 'of 6 040 features are divergently transcribed'),
    ('peaks',
     'Peaks',
     'Regions as called by the original authors'' peak-calling pipeline; not '
     || 'a fixed promoter window'),
    ('array',
     'Array Probes',
     'Regions fixed by the ChIP-chip microarray platform. Not a promoter '
     || 'window and not re-quantifiable over one: the source ships per-target '
     || 'binding ratios with no underlying signal track to re-summarise');
"""


def binding_methods_sql() -> str:
    """
    Return SQL to create and populate the ``binding_methods`` table.

    :returns: ``CREATE TABLE`` + ``INSERT`` SQL string.
    :rtype: str

    """
    return """
CREATE TABLE binding_methods (
    binding_method_id  VARCHAR  PRIMARY KEY,
    display_name       VARCHAR  NOT NULL
);

INSERT INTO binding_methods VALUES
    ('promoter_enrichment', 'Promoter Enrichment'),
    ('peak_calling',        'Peak Calling');
"""


def dataset_registry_sql() -> str:
    """
    Return SQL to create and populate the ``dataset_registry`` table.

    One row per ``db_name`` covering all binding and perturbation datasets.
    Includes HuggingFace coordinates, display metadata, and promoter-set /
    method references for binding datasets.

    Two INSERTs are used: primary rows (``primary_db_name IS NULL``) first,
    variant rows second, so that the self-referential FK constraint is
    satisfied when DuckDB checks it row-by-row.

    :returns: ``CREATE TABLE`` + two ``INSERT`` SQL blocks.
    :rtype: str

    """
    return """
CREATE TABLE dataset_registry (
    db_name              VARCHAR  PRIMARY KEY,
    hf_repo              VARCHAR  NOT NULL,
    hf_config            VARCHAR  NOT NULL,
    data_type            VARCHAR  NOT NULL,
    assay                VARCHAR,
    display_name         VARCHAR,
    base_label           VARCHAR,
    is_primary           BOOLEAN  NOT NULL,
    is_active_default    BOOLEAN  NOT NULL,
    primary_db_name      VARCHAR  REFERENCES dataset_registry(db_name),
    promoter_set_id      VARCHAR  REFERENCES promoter_sets(promoter_set_id),
    binding_method_id    VARCHAR  REFERENCES binding_methods(binding_method_id)
);

-- Pass 1: primary rows (primary_db_name IS NULL) inserted first so the
-- self-referential FK is satisfied when Pass 2 variant rows reference them.
INSERT INTO dataset_registry VALUES
-- binding primaries
-- The 500 bp start-codon window is the primary promoter definition for every
-- promoter-enrichment assay: it is the one definition all three assays share, so
-- making it primary is what lets the figures compare assays without silently
-- comparing promoter definitions too. The Kang/Mindel/intergenic quantifications
-- of the same experiment are variants of it.
('callingcards_500bp',
 'BrentLab/callingcards', 'annotated_feature_reprocess_start_codon_500bp_analysis',
 'binding', 'CallingCards',
 '2026 Calling Cards', '2026 Calling Cards',
 TRUE, TRUE, NULL, '500bp', 'promoter_enrichment'),
-- Harbison's regions come from the microarray, not a promoter definition. It was
-- tagged 'kang', which put it in the Kang column of the promoter-definition grid and
-- implied a comparison that cannot be made: there are no Mindel/500bp/intergenic
-- variants of it and no signal track from which to build any.
('harbison',
 'BrentLab/harbison_2004', 'harbison_2004',
 'binding', 'ChIP-chip',
 '2004 ChIP-chip (Harbison)', '2004 ChIP-chip',
 TRUE, FALSE, NULL, 'array', 'promoter_enrichment'),
('rossi_500bp',
 'BrentLab/rossi_2021', 'rossi_2021_af_combined_start_codon_500bp',
 'binding', 'ChIPexo',
 '2021 ChIP-exo (Rossi)', '2021 ChIP-exo',
 TRUE, TRUE, NULL, '500bp', 'promoter_enrichment'),
('chec_m2025_500bp',
 'BrentLab/mahendrawada_2025', 'chec_mahendrawada_m2025_af_combined_start_codon_500bp',
 'binding', 'ChEC-seq',
 '2025 ChEC-seq (Mahendrawada)', '2025 ChEC-seq',
 TRUE, TRUE, NULL, '500bp', 'promoter_enrichment'),
-- perturbation primaries (all have primary_db_name = NULL)
('kemmeren',
 'BrentLab/kemmeren_2014', 'kemmeren_2014',
 'perturbation', 'TFKO',
 '2014 TFKO (Kemmeren)', '2014 TFKO',
 TRUE, TRUE, NULL, NULL, NULL),
('degron',
 'BrentLab/mahendrawada_2025', 'rnaseq_reprocessed',
 'perturbation', 'RNA-seq',
 '2025 Degron (Mahendrawada)', '2025 Degron',
 TRUE, TRUE, NULL, NULL, NULL),
('hackett',
 'BrentLab/hackett_2020', 'hackett_2020_analysis_set',
 'perturbation', 'overexpression',
 '2020 Overexpression (Hackett)', '2020 Overexpression',
 TRUE, TRUE, NULL, NULL, NULL),
('hu_reimand',
 'BrentLab/hu_2007_reimand_2010', 'hu_2007_reimand_2010',
 'perturbation', 'TFKO',
 '2007 TFKO (Hu)', '2007 TFKO',
 TRUE, FALSE, NULL, NULL, NULL),
('hughes_overexpression',
 'BrentLab/hughes_2006', 'overexpression',
 'perturbation', 'overexpression',
 '2006 Overexpression (Hughes)', '2006 Overexpression',
 TRUE, FALSE, NULL, NULL, NULL),
('hughes_knockout',
 'BrentLab/hughes_2006', 'knockout',
 'perturbation', 'TFKO',
 '2006 Knockout (Hughes)', '2006 Knockout',
 TRUE, FALSE, NULL, NULL, NULL);

-- Pass 2: variant rows — primary rows above now exist so FK is satisfied
INSERT INTO dataset_registry VALUES
-- callingcards variants
('callingcards_mindel',
 'BrentLab/callingcards', 'annotated_feature_reprocess_mindel_analysis',
 'binding', 'CallingCards',
 '2026 Calling Cards (Mindel)', '2026 Calling Cards',
 FALSE, FALSE, 'callingcards_500bp', 'mindel', 'promoter_enrichment'),
('callingcards_kang',
 'BrentLab/callingcards', 'annotated_feature_reprocess_yiming_analysis',
 'binding', 'CallingCards',
 '2026 Calling Cards (Kang)', '2026 Calling Cards',
 FALSE, FALSE, 'callingcards_500bp', 'kang', 'promoter_enrichment'),
('callingcards_intergenic',
 'BrentLab/callingcards', 'annotated_feature_reprocess_intergenic_analysis',
 'binding', 'CallingCards',
 '2026 Calling Cards (Intergenic)', '2026 Calling Cards',
 FALSE, FALSE, 'callingcards_500bp', 'intergenic', 'promoter_enrichment'),
-- rossi variants
('rossi_mindel',
 'BrentLab/rossi_2021', 'rossi_2021_af_combined_mindel',
 'binding', 'ChIPexo',
 '2021 ChIP-exo (Rossi, Mindel)', '2021 ChIP-exo',
 FALSE, FALSE, 'rossi_500bp', 'mindel', 'promoter_enrichment'),
('rossi',
 'BrentLab/rossi_2021', 'rossi_2021_af_combined',
 'binding', 'ChIPexo',
 '2021 ChIP-exo (Rossi, Kang)', '2021 ChIP-exo',
 FALSE, FALSE, 'rossi_500bp', 'kang', 'promoter_enrichment'),
('rossi_intergenic',
 'BrentLab/rossi_2021', 'rossi_2021_af_combined_intergenic',
 'binding', 'ChIPexo',
 '2021 ChIP-exo (Rossi, Intergenic)', '2021 ChIP-exo',
 FALSE, FALSE, 'rossi_500bp', 'intergenic', 'promoter_enrichment'),
('rossi_peaks',
 'BrentLab/rossi_2021', 'yep_filtered_peaks_combined',
 'binding', 'ChIPexo',
 '2021 ChIP-exo Peaks', '2021 ChIP-exo',
 FALSE, FALSE, 'rossi_500bp', 'peaks', 'peak_calling'),
('rossi_peaks_kang',
 'BrentLab/rossi_2021', 'macs_kang',
 'binding', 'ChIPexo',
 '2021 ChIP-exo Peaks (MACS, Kang)', '2021 ChIP-exo',
 FALSE, FALSE, 'rossi_500bp', 'kang', 'peak_calling'),
('rossi_peaks_mindel',
 'BrentLab/rossi_2021', 'macs_mindel',
 'binding', 'ChIPexo',
 '2021 ChIP-exo Peaks (MACS, Mindel)', '2021 ChIP-exo',
 FALSE, FALSE, 'rossi_500bp', 'mindel', 'peak_calling'),
('rossi_peaks_500bp',
 'BrentLab/rossi_2021', 'macs_bp500',
 'binding', 'ChIPexo',
 '2021 ChIP-exo Peaks (MACS, 500bp)', '2021 ChIP-exo',
 FALSE, FALSE, 'rossi_500bp', '500bp', 'peak_calling'),
('rossi_peaks_intergenic',
 'BrentLab/rossi_2021', 'macs_intergenic',
 'binding', 'ChIPexo',
 '2021 ChIP-exo Peaks (MACS, Intergenic)', '2021 ChIP-exo',
 FALSE, FALSE, 'rossi_500bp', 'intergenic', 'peak_calling'),
-- chec_m2025 variants
('chec_m2025_mindel',
 'BrentLab/mahendrawada_2025', 'chec_mahendrawada_m2025_af_combined_mindel',
 'binding', 'ChEC-seq',
 '2025 ChEC-seq (Mahendrawada, Mindel)', '2025 ChEC-seq',
 FALSE, FALSE, 'chec_m2025_500bp', 'mindel', 'promoter_enrichment'),
('chec_m2025',
 'BrentLab/mahendrawada_2025', 'chec_mahendrawada_m2025_af_combined',
 'binding', 'ChEC-seq',
 '2025 ChEC-seq (Mahendrawada, Kang)', '2025 ChEC-seq',
 FALSE, FALSE, 'chec_m2025_500bp', 'kang', 'promoter_enrichment'),
('chec_m2025_intergenic',
 'BrentLab/mahendrawada_2025', 'chec_mahendrawada_m2025_af_combined_intergenic',
 'binding', 'ChEC-seq',
 '2025 ChEC-seq (Mahendrawada, Intergenic)', '2025 ChEC-seq',
 FALSE, FALSE, 'chec_m2025_500bp', 'intergenic', 'promoter_enrichment'),
('chec_m2025_peaks',
 'BrentLab/mahendrawada_2025', 'mahendrawada_chec_seq',
 'binding', 'ChEC-seq',
 '2025 ChEC-seq Peaks (Mahendrawada)', '2025 ChEC-seq',
 FALSE, FALSE, 'chec_m2025_500bp', 'peaks', 'peak_calling'),
('chec_m2025_peaks_kang',
 'BrentLab/mahendrawada_2025', 'kang_peaks',
 'binding', 'ChEC-seq',
 '2025 ChEC-seq Peaks (HOMER, Kang)', '2025 ChEC-seq',
 FALSE, FALSE, 'chec_m2025_500bp', 'kang', 'peak_calling'),
('chec_m2025_peaks_mindel',
 'BrentLab/mahendrawada_2025', 'mindel_peaks',
 'binding', 'ChEC-seq',
 '2025 ChEC-seq Peaks (HOMER, Mindel)', '2025 ChEC-seq',
 FALSE, FALSE, 'chec_m2025_500bp', 'mindel', 'peak_calling'),
('chec_m2025_peaks_500bp',
 'BrentLab/mahendrawada_2025', 'bp500_peaks',
 'binding', 'ChEC-seq',
 '2025 ChEC-seq Peaks (HOMER, 500bp)', '2025 ChEC-seq',
 FALSE, FALSE, 'chec_m2025_500bp', '500bp', 'peak_calling'),
('chec_m2025_peaks_intergenic',
 'BrentLab/mahendrawada_2025', 'intergenic_peaks',
 'binding', 'ChEC-seq',
 '2025 ChEC-seq Peaks (HOMER, Intergenic)', '2025 ChEC-seq',
 FALSE, FALSE, 'chec_m2025_500bp', 'intergenic', 'peak_calling');
"""


def comparative_registry_sql() -> str:
    """
    Return SQL to create and populate the ``comparative_dataset_registry`` table.

    :returns: ``CREATE TABLE`` + ``INSERT`` SQL string.
    :rtype: str

    """
    return """
CREATE TABLE comparative_dataset_registry (
    analysis_name    VARCHAR  PRIMARY KEY,
    provenance       VARCHAR  NOT NULL,
    description      VARCHAR,
    hf_repo          VARCHAR,
    hf_config        VARCHAR
);

INSERT INTO comparative_dataset_registry VALUES
    ('dto',
     'hf_parquet',
     'Directional transcription overlap (DTO) empirical p-values',
     'BrentLab/yeast_comparative_analysis',
     'dto'),
    ('topn_results',
     'computed',
     'Top-N-by-binding responsive ratio for (binding, perturbation, regulator) triples',
     NULL,
     NULL),
    ('correlations',
     'computed',
     'Pairwise Pearson or Spearman correlations between samples within the '
     || 'same data type',
     NULL,
     NULL);
"""


def column_metadata_sql(vdb: VirtualDB) -> str:
    """
    Return SQL to create and populate the ``dataset_column_metadata`` table.

    Queries VirtualDB for each dataset's column metadata, applies
    :data:`~tfbpshiny.utils.vdb_init.HIDDEN_FILTER_FIELDS`, and classifies
    columns as ``'condition'`` or ``'upstream'``.  The resulting table replaces
    ``vdb.get_column_metadata()`` at app startup.

    :param vdb: VirtualDB instance with all dataset views registered.
    :returns: ``CREATE TABLE`` + ``INSERT`` SQL string.
    :rtype: str

    """
    hidden_global = HIDDEN_FILTER_FIELDS.get("*", set())
    rows: list[str] = []

    for db_name in vdb.get_datasets():
        db_meta = vdb.get_column_metadata(db_name) or {}
        hidden = hidden_global | HIDDEN_FILTER_FIELDS.get(db_name, set())

        condition_cols = [
            col
            for col, m in db_meta.items()
            if m.role == "experimental_condition"
            and m.level_definitions is not None
            and col not in hidden
        ]
        upstream_cols = [
            col
            for col, m in db_meta.items()
            if col not in condition_cols
            and col not in hidden
            and col != "sample_id"
            and m.role not in ("regulator_identifier", "target_identifier")
            and m.level_definitions is None
        ]
        for col in condition_cols:
            safe_col = col.replace("'", "''")
            safe_db = db_name.replace("'", "''")
            rows.append(f"('{safe_db}', '{safe_col}', 'condition')")
        for col in upstream_cols:
            safe_col = col.replace("'", "''")
            safe_db = db_name.replace("'", "''")
            rows.append(f"('{safe_db}', '{safe_col}', 'upstream')")

    values_clause = (
        ",\n    ".join(rows) if rows else "('__placeholder__', '__none__', 'condition')"
    )
    return f"""
CREATE TABLE dataset_column_metadata (
    db_name     VARCHAR NOT NULL,
    column_name VARCHAR NOT NULL,
    role        VARCHAR NOT NULL,
    PRIMARY KEY (db_name, column_name)
);

INSERT INTO dataset_column_metadata VALUES
    {values_clause};
"""


def sample_regulator_sql(db_names: list[str]) -> str:
    """
    Return SQL creating and populating the ``sample_regulator`` lookup table.

    Maps ``(db_name, sample_id) -> regulator_locus_tag`` across every dataset whose
    ``{db_name}_meta`` table carries a regulator column. Two consumers need it:

    * resolving ``dto.regulator_locus_tag`` -- the DTO source carries only composite
      ``repo;config;sample_id`` identifiers, with no regulator column of its own;
    * computing the DTO denominator, which is the count of regulators present in
      *both* a binding and a perturbation dataset.

    ``sample_id`` is cast to VARCHAR because the underlying meta tables disagree on
    type (VARCHAR for callingcards and degron, INTEGER elsewhere) and the composite
    identifiers DTO ships are strings.

    Rows with a NULL regulator are skipped so the column can be ``NOT NULL``.

    :param db_names: Dataset names whose ``{db_name}_meta`` table exists **and** has a
        ``regulator_locus_tag`` column.
    :returns: ``CREATE TABLE`` + ``INSERT`` SQL string.
    :rtype: str

    """
    ddl = """
CREATE TABLE sample_regulator (
    db_name             VARCHAR NOT NULL,
    sample_id           VARCHAR NOT NULL,
    regulator_locus_tag VARCHAR NOT NULL,
    PRIMARY KEY (db_name, sample_id)
);
"""
    if not db_names:
        return ddl

    selects = [
        f"""SELECT '{db.replace("'", "''")}' AS db_name,
       CAST(sample_id AS VARCHAR)          AS sample_id,
       regulator_locus_tag
FROM "{db}_meta"
WHERE regulator_locus_tag IS NOT NULL"""
        for db in db_names
    ]
    # DISTINCT because a meta table may carry several rows per sample (e.g. one per
    # condition), which would otherwise violate the primary key.
    union = "\n UNION ALL\n".join(selects)
    return f"""{ddl}
INSERT INTO sample_regulator
SELECT DISTINCT ON (db_name, sample_id) db_name, sample_id, regulator_locus_tag
FROM (
{union}
);
"""
