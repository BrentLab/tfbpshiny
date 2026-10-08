"""
SQL generators for the DTO (direct target overlap) comparison table.

The DTO data is sourced from the HuggingFace Parquet stored in
``BrentLab/yeast_comparative_analysis;dto``.

Note the source view is ``dto_expanded``, **not** ``dto``. labretriever treats any
dataset carrying a ``links:`` block as *comparative* and deliberately registers only
``__dto_parquet`` plus ``<db_name>_expanded`` for it -- no bare public ``dto`` view is
ever created (see ``labretriever/virtual_db.py::_register_raw_view``). Reading from
``dto_expanded`` also gets us the ``*_id_source`` columns for free: they resolve each
composite identifier's ``repo;config`` prefix to our own ``db_name`` using the
``links:`` block in ``brentlab_yeast_collection.yaml``.

"""

from __future__ import annotations

#: Target columns for the ``dto`` insert, in the order ``dto_select_sql()`` emits them.
#: ``regulator_locus_tag`` is deliberately absent -- it is filled afterwards by
#: ``dto_resolve_regulators_sql()``.
DTO_INSERT_COLUMNS: list[str] = [
    "binding_source_sample",
    "perturbation_source_sample",
    "binding_db",
    "binding_sample_id",
    "perturbation_db",
    "perturbation_sample_id",
    "pr_ranking_column",
    "dto_empirical_pvalue",
    "dto_fdr",
    "binding_set_size",
    "perturbation_set_size",
]


def dto_schema_sql() -> str:
    """
    Return the ``CREATE TABLE dto`` DDL.

    Column naming mirrors ``topn_results`` (``*_source_sample`` for the composite
    identifiers, plus a resolved ``regulator_locus_tag``) so the Comparison module can
    query both tables through the same prefix-matching pattern.

    ``regulator_locus_tag`` is nullable at create time; it is populated from
    ``sample_regulator`` immediately after load.

    :returns: ``CREATE TABLE dto (…)`` SQL string.
    :rtype: str

    """
    return """
CREATE TABLE dto (
    binding_source_sample       VARCHAR  NOT NULL,
    perturbation_source_sample  VARCHAR  NOT NULL,
    binding_db                  VARCHAR  NOT NULL,
    binding_sample_id           VARCHAR  NOT NULL,
    perturbation_db             VARCHAR  NOT NULL,
    perturbation_sample_id      VARCHAR  NOT NULL,
    regulator_locus_tag         VARCHAR,
    pr_ranking_column           VARCHAR  NOT NULL,
    dto_empirical_pvalue        DOUBLE,
    dto_fdr                     DOUBLE,
    binding_set_size            DOUBLE,
    perturbation_set_size       DOUBLE,
    PRIMARY KEY (binding_source_sample, perturbation_source_sample, pr_ranking_column)
);
"""


def dto_select_sql() -> str:
    """
    Return a SELECT that reads the DTO rows out of VirtualDB.

    Reads ``dto_expanded``, whose ``binding_id_source`` / ``perturbation_id_source``
    columns are already aliased to our ``db_name`` values, and whose ``*_id_id``
    columns hold the third (sample id) component of each composite identifier.

    Columns are projected explicitly rather than ``SELECT *`` so the table holds only
    the columns the app reads; the source also carries ``binding_rank_threshold`` and
    ``perturbation_rank_threshold``, which nothing uses.

    :returns: ``SELECT`` SQL string.
    :rtype: str

    """
    return """
SELECT
    binding_id                          AS binding_source_sample,
    perturbation_id                     AS perturbation_source_sample,
    binding_id_source                   AS binding_db,
    CAST(binding_id_id AS VARCHAR)      AS binding_sample_id,
    perturbation_id_source              AS perturbation_db,
    CAST(perturbation_id_id AS VARCHAR) AS perturbation_sample_id,
    pr_ranking_column,
    dto_empirical_pvalue,
    dto_fdr,
    binding_set_size,
    perturbation_set_size
FROM dto_expanded
"""


def dto_resolve_regulators_sql() -> str:
    """
    Return SQL populating ``dto.regulator_locus_tag`` from ``sample_regulator``.

    DTO ships no regulator column -- only composite ``repo;config;sample_id`` strings
    -- so the regulator is recovered by joining the binding side's ``(db_name,
    sample_id)`` against the ``sample_regulator`` lookup built from every ``*_meta``
    table. Every DTO row pairs a binding and perturbation sample for the *same*
    regulator, so the binding side alone is sufficient.

    :returns: ``UPDATE`` SQL string.
    :rtype: str

    """
    return """
UPDATE dto
SET regulator_locus_tag = sr.regulator_locus_tag
FROM sample_regulator sr
WHERE sr.db_name = dto.binding_db
  AND sr.sample_id = dto.binding_sample_id;
"""
