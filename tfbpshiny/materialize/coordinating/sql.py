"""
SQL generators for the coordinating layer of the materialized DuckDB schema.

All functions return pure SQL strings (no side effects) so they can be called
from a Jupyter notebook to inspect output before running the full pipeline.
The coordinator is the only code that calls ``.execute()``.

"""

from __future__ import annotations

from labretriever import VirtualDB

from tfbpshiny.config import AppConfig, load_app_config
from tfbpshiny.utils.vdb_init import HIDDEN_FILTER_FIELDS


def schema_version_sql(version: int, git_sha: str | None) -> str:
    """
    Return SQL creating the one-row ``schema_version`` table.

    The app reads ``version`` at startup and compares it with
    :data:`tfbpshiny.datasets.SCHEMA_VERSION`; ``built_at`` and ``git_sha`` say which
    build produced the file.

    :param version: The schema version this build writes.
    :param git_sha: Commit the materializer ran from, or ``None`` outside a checkout.
    :returns: ``CREATE TABLE`` + ``INSERT`` SQL string.

    """
    sha = "NULL" if git_sha is None else "'" + git_sha.replace("'", "''") + "'"
    return f"""
CREATE TABLE schema_version (
    version   INTEGER   NOT NULL,
    built_at  TIMESTAMP NOT NULL,
    git_sha   VARCHAR
);
INSERT INTO schema_version VALUES ({int(version)}, now()::TIMESTAMP, {sha});
"""


def _lit(value: object) -> str:
    """A SQL literal for a config value: NULL, TRUE/FALSE, or a quoted string."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return "'" + str(value).replace("'", "''") + "'"


def promoter_sets_sql(config: AppConfig | None = None) -> str:
    """
    Return SQL to create and populate the ``promoter_sets`` table.

    Rows are the ``tfbpshiny.promoter_sets`` section of the collection config.

    :param config: Parsed collection config; the packaged one when ``None``.
    :returns: ``CREATE TABLE`` + ``INSERT`` SQL string.

    """
    config = config or load_app_config()
    rows = ",\n".join(
        f"    ({_lit(v.id)}, {_lit(v.display_name)}, {_lit(v.description or None)})"
        for v in config.promoter_sets.values()
    )
    return f"""
CREATE TABLE promoter_sets (
    promoter_set_id  VARCHAR  PRIMARY KEY,
    display_name     VARCHAR  NOT NULL,
    description      VARCHAR
);

INSERT INTO promoter_sets VALUES
{rows};
"""


def binding_methods_sql(config: AppConfig | None = None) -> str:
    """
    Return SQL to create and populate the ``binding_methods`` table.

    Rows are the ``tfbpshiny.binding_methods`` section of the collection config.

    :param config: Parsed collection config; the packaged one when ``None``.
    :returns: ``CREATE TABLE`` + ``INSERT`` SQL string.

    """
    config = config or load_app_config()
    rows = ",\n".join(
        f"    ({_lit(v.id)}, {_lit(v.display_name)})"
        for v in config.binding_methods.values()
    )
    return f"""
CREATE TABLE binding_methods (
    binding_method_id  VARCHAR  PRIMARY KEY,
    display_name       VARCHAR  NOT NULL
);

INSERT INTO binding_methods VALUES
{rows};
"""


def dataset_registry_sql(config: AppConfig | None = None) -> str:
    """
    Return SQL to create and populate the ``dataset_registry`` table.

    One row per binding or perturbation dataset declared in the collection config,
    from its merged labretriever ``tags`` (see :mod:`tfbpshiny.config`).

    Primaries are inserted in a statement of their own before the variants, so the
    self-referential FK is satisfied when DuckDB checks the second statement.

    :param config: Parsed collection config; the packaged one when ``None``.
    :returns: ``CREATE TABLE`` + ``INSERT`` SQL string.

    """
    config = config or load_app_config()

    def _values(primaries: bool) -> str:
        return ",\n".join(
            "("
            + ", ".join(
                _lit(v)
                for v in (
                    d.db_name,
                    d.hf_repo,
                    d.hf_config,
                    d.data_type,
                    d.assay,
                    d.display_name,
                    d.base_label,
                    d.is_primary,
                    d.is_active_default,
                    d.primary_db_name,
                    d.promoter_set_id,
                    d.binding_method_id,
                )
            )
            + ")"
            for d in config.datasets.values()
            if d.is_primary == primaries
        )

    return f"""
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

-- Primaries first, in their own statement: the FK is checked per statement.
INSERT INTO dataset_registry VALUES
{_values(True)};

INSERT INTO dataset_registry VALUES
{_values(False)};
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
