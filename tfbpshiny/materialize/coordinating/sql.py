"""
SQL generators for the coordinating layer of the materialized DuckDB schema.

All functions return pure SQL strings (no side effects) so they can be called
from a Jupyter notebook to inspect output before running the full pipeline.
The coordinator is the only code that calls ``.execute()``.

"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from labretriever import VirtualDB

from tfbpshiny.datasets import BINDING_METHODS, PROMOTER_SETS
from tfbpshiny.utils.vdb_init import hidden_filter_fields


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
    """A SQL literal: NULL, TRUE/FALSE, or a quoted string."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return "'" + str(value).replace("'", "''") + "'"


# ---------------------------------------------------------------------------
# Dataset registry, from the collection config's tags
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegistryRow:
    """
    One ``dataset_registry`` row, from a dataset's merged labretriever tags.

    The tags tfbpshiny reads (all strings): ``data_type`` (``binding`` or
    ``perturbation``; datasets without one, such as ``dto``, are not registered),
    ``assay``, ``display_name``, ``base_label``, ``primary`` (the primary this
    dataset is a variant of; a dataset naming itself or nothing is a primary),
    ``promoter_set`` and
    ``binding_method`` (binding only; keys of :data:`tfbpshiny.datasets.PROMOTER_SETS` /
    :data:`~tfbpshiny.datasets.BINDING_METHODS`), ``active_default`` (``"true"`` to
    switch the dataset on in a new session), and on primaries ``color`` and
    ``peak_calling_note``. ``description`` is labretriever's dataset description:
    the collection config's, else the DataCard's.

    """

    db_name: str
    hf_repo: str
    hf_config: str
    data_type: str
    assay: str
    display_name: str
    base_label: str
    primary_db_name: str | None
    is_active_default: bool
    promoter_set_id: str | None
    binding_method_id: str | None
    color: str | None
    peak_calling_note: str | None
    description: str | None = None

    @property
    def is_primary(self) -> bool:
        return self.primary_db_name is None


def registry_rows(vdb: Any) -> list[RegistryRow]:
    """
    Read and check every binding/perturbation dataset's tags.

    labretriever merges repository- and dataset-level tags and resolves ``db_name``;
    this only checks that the tags tfbpshiny relies on are present and coherent.

    :param vdb: VirtualDB (anything with ``get_datasets``, ``get_tags`` and
        ``db_name_map``).
    :returns: Rows in ``db_name`` order.
    :raises ValueError: On a missing label, an unknown promoter set or method, a
        promoter set on perturbation data, an ``active_default`` other than
        true/false, or a variant that is not of a primary with the same data type and
        ``base_label``.

    """
    rows: dict[str, RegistryRow] = {}
    for db in sorted(vdb.get_datasets()):
        tags = vdb.get_tags(db)
        data_type = tags.get("data_type")
        if data_type not in ("binding", "perturbation"):
            continue
        missing = [
            k for k in ("assay", "display_name", "base_label") if not tags.get(k)
        ]
        if missing:
            raise ValueError(f"{db}: missing tag(s) {missing}")
        ps, method = tags.get("promoter_set"), tags.get("binding_method")
        if data_type == "binding":
            if ps not in PROMOTER_SETS:
                raise ValueError(f"{db}: unknown promoter_set {ps!r}")
            if method not in BINDING_METHODS:
                raise ValueError(f"{db}: unknown binding_method {method!r}")
        elif ps or method:
            raise ValueError(f"{db}: perturbation data has no promoter set or method")
        active = str(tags.get("active_default", "false")).lower()
        if active not in ("true", "false"):
            raise ValueError(f"{db}: active_default must be true or false")
        primary = tags.get("primary")
        hf_repo, hf_config = vdb.db_name_map[db]
        rows[db] = RegistryRow(
            db_name=db,
            hf_repo=hf_repo,
            hf_config=hf_config,
            data_type=data_type,
            assay=tags["assay"],
            display_name=tags["display_name"],
            base_label=tags["base_label"],
            primary_db_name=None if primary in (None, "", db) else primary,
            is_active_default=active == "true",
            promoter_set_id=ps,
            binding_method_id=method,
            color=tags.get("color"),
            peak_calling_note=tags.get("peak_calling_note"),
            description=vdb.get_dataset_description(db),
        )
    for row in rows.values():
        p = row.primary_db_name
        if p is None:
            continue
        if p not in rows or not rows[p].is_primary:
            raise ValueError(f"{row.db_name}: primary {p!r} is not a primary dataset")
        if (rows[p].data_type, rows[p].base_label) != (row.data_type, row.base_label):
            raise ValueError(
                f"{row.db_name}: a variant must share its primary's data_type and"
                " base_label"
            )
    return list(rows.values())


def promoter_set_descriptions(vdb: Any) -> dict[str, str]:
    """
    Description of every promoter set in :data:`tfbpshiny.datasets.PROMOTER_SETS`.

    A promoter set that names a ``region_set`` takes that region set's description
    from labretriever; the others carry their own.

    :param vdb: VirtualDB (anything with ``get_datasets`` and ``get_region_sets``).
    :returns: ``promoter_set_id -> description`` (whitespace normalised).
    :raises ValueError: If a named region set is not declared in the collection.

    """
    region_sets: dict[str, Any] = {}
    for db in vdb.get_datasets():
        region_sets.update(vdb.get_region_sets(db))
    out: dict[str, str] = {}
    for ps, v in PROMOTER_SETS.items():
        if v.region_set is None:
            text = v.description or ""
        elif v.region_set in region_sets:
            text = region_sets[v.region_set].description or ""
        else:
            raise ValueError(
                f"promoter set {ps!r}: region set {v.region_set!r} is not declared in"
                " the collection's genome_resources"
            )
        out[ps] = " ".join(text.split())
    return out


def promoter_sets_sql(descriptions: dict[str, str]) -> str:
    """
    Return SQL to create and populate the ``promoter_sets`` table.

    :param descriptions: From :func:`promoter_set_descriptions`.
    :returns: ``CREATE TABLE`` + ``INSERT`` SQL string.

    """
    rows = ",\n".join(
        "    ("
        + ", ".join(
            _lit(x)
            for x in (ps, v.display_name, descriptions.get(ps), v.color, v.reference)
        )
        + ")"
        for ps, v in PROMOTER_SETS.items()
    )
    return f"""
CREATE TABLE promoter_sets (
    promoter_set_id  VARCHAR  PRIMARY KEY,
    display_name     VARCHAR  NOT NULL,
    description      VARCHAR,
    color            VARCHAR,
    reference        VARCHAR
);

INSERT INTO promoter_sets VALUES
{rows};
"""


def binding_methods_sql() -> str:
    """
    Return SQL to create and populate the ``binding_methods`` table.

    :returns: ``CREATE TABLE`` + ``INSERT`` SQL string.

    """
    rows = ",\n".join(
        f"    ({_lit(m)}, {_lit(v.display_name)}, {_lit(v.color)})"
        for m, v in BINDING_METHODS.items()
    )
    return f"""
CREATE TABLE binding_methods (
    binding_method_id  VARCHAR  PRIMARY KEY,
    display_name       VARCHAR  NOT NULL,
    color              VARCHAR
);

INSERT INTO binding_methods VALUES
{rows};
"""


def dataset_registry_sql(rows: list[RegistryRow]) -> str:
    """
    Return SQL to create and populate the ``dataset_registry`` table.

    Primaries are inserted in a statement of their own before the variants, so the
    self-referential FK is satisfied when DuckDB checks the second statement.

    :param rows: From :func:`registry_rows`.
    :returns: ``CREATE TABLE`` + ``INSERT`` SQL string.

    """

    def _values(primaries: bool) -> str:
        return ",\n".join(
            "("
            + ", ".join(
                _lit(v)
                for v in (
                    r.db_name,
                    r.hf_repo,
                    r.hf_config,
                    r.data_type,
                    r.assay,
                    r.display_name,
                    r.base_label,
                    r.is_primary,
                    r.is_active_default,
                    r.primary_db_name,
                    r.promoter_set_id,
                    r.binding_method_id,
                    r.color,
                    r.peak_calling_note,
                    r.description,
                )
            )
            + ")"
            for r in rows
            if r.is_primary == primaries
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
    binding_method_id    VARCHAR  REFERENCES binding_methods(binding_method_id),
    color                VARCHAR,
    peak_calling_note    VARCHAR,
    description          VARCHAR
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
     'Dual threshold optimization (DTO) empirical p-values',
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

    One row per filterable metadata column of every dataset, from labretriever's
    ``get_column_metadata``, with :func:`~tfbpshiny.utils.vdb_init.hidden_filter_fields`
    left out. ``role`` is ``'condition'`` for an experimental-condition column with
    per-level definitions and ``'upstream'`` for any other filterable column.
    ``description`` and ``level_definitions`` (a JSON object, level value to
    definition) label the filter modal's controls.

    :param vdb: VirtualDB instance with all dataset views registered.
    :returns: ``CREATE TABLE`` + ``INSERT`` SQL string.

    """
    rows: list[str] = []

    for db_name in vdb.get_datasets():
        db_meta = vdb.get_column_metadata(db_name) or {}
        hidden = hidden_filter_fields(db_name, vdb.get_tags(db_name).get("primary"))
        for col, m in db_meta.items():
            if col in hidden or col == "sample_id":
                continue
            if m.role == "experimental_condition" and m.level_definitions is not None:
                role = "condition"
            elif (
                m.role not in ("regulator_identifier", "target_identifier")
                and m.level_definitions is None
            ):
                role = "upstream"
            else:
                continue
            levels = (
                json.dumps(m.level_definitions, sort_keys=True)
                if m.level_definitions is not None
                else None
            )
            rows.append(
                "("
                + ", ".join(
                    _lit(v) for v in (db_name, col, role, m.description, levels)
                )
                + ")"
            )

    insert = (
        "INSERT INTO dataset_column_metadata VALUES\n    " + ",\n    ".join(rows) + ";"
        if rows
        else ""
    )
    return f"""
CREATE TABLE dataset_column_metadata (
    db_name           VARCHAR NOT NULL,
    column_name       VARCHAR NOT NULL,
    role              VARCHAR NOT NULL,
    description       VARCHAR,
    level_definitions VARCHAR,
    PRIMARY KEY (db_name, column_name)
);

{insert}
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
