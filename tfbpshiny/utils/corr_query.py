"""Shared DuckDB-based correlation query helper for binding and perturbation
workspaces."""

from __future__ import annotations

import logging
from typing import Any

import duckdb
import pandas as pd

logger = logging.getLogger("shiny")

#: (variant, field) pairs already warned about, so the warning is logged once rather
#: than on every change to the filter state.
_WARNED_MISSING: set[tuple[str, str]] = set()


def expand_filters_to_variants(
    conn: duckdb.DuckDBPyConnection,
    filters: dict[str, Any],
    registry: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """
    Give every variant dataset its primary's sample filter.

    The selection tab shows, and edits, filters on the *primary* datasets
    (``rossi_500bp``, ``chec_m2025_500bp``, ...). The alternate promoter-set and
    peak-calling variants of an assay (``rossi_mindel``, ``rossi_peaks_kang``, ...) are
    the same experiment, and consumers look a filter up under the variant's own name --
    so without this a variant silently keeps every sample, including the ones the
    default filter exists to remove (heat-shock, non-standard conditions), and a
    regulator appears several times.

    A variant takes its primary's filter **in place of** any entry of its own, so an
    edit made on the selection tab reaches every variant. Only the filter fields that
    the variant's metadata actually has are copied: the authors' ChEC-seq peak calls
    carry no condition column, so the condition filter cannot apply to them and is
    left off rather than raising. A variant with no applicable field is left
    unfiltered.

    :param conn: DuckDB connection holding ``dataset_registry`` and the ``{db}_meta``
        tables.
    :param filters: Committed filters, keyed by db_name (usually primaries only).
    :param registry: ``db_name`` / ``primary_db_name`` rows to use instead of reading
        ``dataset_registry`` from ``conn``.
    :returns: A new dict: ``filters`` plus an entry for each variant whose primary has
        one. The input is not modified.

    """
    out = dict(filters)
    if registry is None:
        variants = conn.execute(
            "SELECT db_name, primary_db_name FROM dataset_registry"
            " WHERE primary_db_name IS NOT NULL AND primary_db_name != db_name"
        ).fetchall()
    else:
        variants = [
            (str(v), str(p))
            for v, p in zip(registry["db_name"], registry["primary_db_name"])
            if pd.notna(p) and p != v
        ]
    wanted = [v for v, primary in variants if filters.get(primary)]
    if not wanted:
        return out
    meta_cols: dict[str, set[str]] = {}
    for table, column in conn.execute(
        "SELECT table_name, column_name FROM information_schema.columns"
        " WHERE table_name LIKE '%\\_meta' ESCAPE '\\'"
    ).fetchall():
        meta_cols.setdefault(table, set()).add(column)
    for variant, primary in variants:
        spec = filters.get(primary)
        if not spec:
            continue
        if f"{variant}_meta" not in meta_cols:
            # No metadata table for this variant in this database (a scratch workspace
            # holds only the datasets it needs): nothing to filter, nothing to warn
            # about.
            out.pop(variant, None)
            continue
        have = meta_cols[f"{variant}_meta"]
        inherited = {field: s for field, s in spec.items() if field in have}
        for field in spec:
            if field not in have and (variant, field) not in _WARNED_MISSING:
                _WARNED_MISSING.add((variant, field))
                logger.warning(
                    "default filter field %r of %s cannot be applied to its variant %s:"
                    " %s_meta has no such column, so that variant is not filtered on it"
                    " (declare a constant column in the collection yaml if every sample"
                    " has the same value)",
                    field,
                    primary,
                    variant,
                    variant,
                )
        if inherited:
            out[variant] = inherited
        else:
            out.pop(variant, None)
    return out


def get_filtered_sample_ids(
    conn: duckdb.DuckDBPyConnection,
    db_name: str,
    filters: dict[str, Any] | None,
) -> list[str]:
    """
    Return CAST(sample_id AS VARCHAR) from {db_name}_meta matching filters.

    :param conn: Open read-only DuckDB connection.
    :param db_name: Dataset name whose ``{db_name}_meta`` table to query.
    :param filters: Filter spec dict (column -> {type, value}), or ``None``.
    :returns: List of sample ID strings.

    """
    where_clauses: list[str] = []
    params: list[Any] = []
    for field, spec in (filters or {}).items():
        kind = spec["type"]
        val = spec["value"]
        if kind == "categorical":
            phs = ", ".join(["?"] * len(val))
            where_clauses.append(f'CAST("{field}" AS VARCHAR) IN ({phs})')
            params.extend([str(v) for v in val])
        elif kind == "numeric":
            where_clauses.append(f'"{field}" BETWEEN ? AND ?')
            params.extend([val[0], val[1]])
        elif kind == "bool":
            where_clauses.append(f'"{field}" = ?')
            params.append(bool(val))
    where = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
    sql = f"SELECT CAST(sample_id AS VARCHAR) AS sid FROM {db_name}_meta {where}"
    return conn.execute(sql, params).df()["sid"].tolist()


def fetch_corr_pairs(
    conn: duckdb.DuckDBPyConnection,
    pairs: list[tuple[str, str]],
    filters: dict[str, Any],
    method: str,
    score_type: str,
    comparison_type: str = "binding",
) -> dict[tuple[str, str], pd.DataFrame]:
    """
    Fetch pre-computed correlations from the correlations table for a list of pairs.

    :param conn: Read-only DuckDB connection to the materialized database.
    :param pairs: List of (db_a, db_b) dataset name pairs.
    :param filters: dataset_filters dict keyed by db_name.
    :param method: 'pearson' or 'spearman'.
    :param score_type: 'effect', 'pvalue', or 'log10pval' — must match a
        ``score_type`` value materialized in the ``correlations`` table.
    :param comparison_type: 'binding' or 'perturbation'.
    :returns: Dict mapping (db_a, db_b) to DataFrame with regulator_locus_tag,
        correlation.

    """
    result: dict[tuple[str, str], pd.DataFrame] = {}
    empty = pd.DataFrame(columns=["regulator_locus_tag", "correlation"])
    for db_a, db_b in pairs:
        a_clause, a_params = sample_filter_clause(
            conn, db_a, filters.get(db_a), "sample_a"
        )
        b_clause, b_params = sample_filter_clause(
            conn, db_b, filters.get(db_b), "sample_b"
        )
        sql = f"""
        SELECT regulator_locus_tag, AVG(correlation) AS correlation
        FROM correlations
        WHERE comparison_type = ?
          AND method = ?
          AND score_type = ?
          AND db_a = ?
          AND db_b = ?{a_clause}{b_clause}
        GROUP BY regulator_locus_tag
        """
        params: list[Any] = (
            [comparison_type, method, score_type, db_a, db_b] + a_params + b_params
        )
        try:
            df = conn.execute(sql, params).df()
        except duckdb.Error:
            logger.exception("fetch_corr_pairs: %s x %s", db_a, db_b)
            df = empty.copy()
        result[(db_a, db_b)] = df
    return result


def sample_in_clause(column: str, ids: list[str] | None) -> tuple[str, list]:
    """
    SQL fragment restricting ``column`` to an already-resolved sample allow-list.

    :param column: SQL expression yielding the sample id to constrain.
    :param ids: The allowed sample ids; ``None`` means the dataset has no filter, so no
        restriction is emitted.
    :returns: ``(sql_fragment, params)``. ``("", [])`` for no filter; ``(" AND FALSE",
        [])`` for an empty allow-list, so that "nothing passes" is explicit rather than
        the restriction silently dropping away.

    """
    if ids is None:
        return "", []
    if not ids:
        return " AND FALSE", []
    return f" AND {column} IN ({', '.join(['?'] * len(ids))})", list(ids)


def sample_filter_clause(
    conn: duckdb.DuckDBPyConnection,
    db_name: str,
    filters: dict | None,
    column: str,
) -> tuple[str, list]:
    """
    Build a SQL fragment restricting ``column`` to the samples passing ``filters``.

    Without this, a dataset's samples are pooled indiscriminately -- Hackett would
    contribute all 1,543 timepoint samples rather than the 193 at the default 45 min
    timepoint, which materially changes every figure that medians across samples.

    Returns ``("", [])`` when the dataset has no filter, so callers can splice the
    fragment in unconditionally.

    :param conn: Read-only DuckDB connection.
    :param db_name: Dataset whose ``{db_name}_meta`` supplies the sample ids.
    :param filters: Filter spec for this dataset, or ``None``.
    :param column: SQL expression yielding the sample id to constrain.
    :returns: ``(sql_fragment, params)``.

    """
    if not filters:
        return "", []
    return sample_in_clause(column, get_filtered_sample_ids(conn, db_name, filters))


def per_dataset_sample_clause(
    conn: duckdb.DuckDBPyConnection,
    db_names: list[str],
    filters: dict,
    db_column: str,
    sample_column: str,
) -> tuple[str, list]:
    """
    Build SQL restricting each of several datasets to its own filtered samples.

    For queries that mix datasets in one result set (a binding series per dataset, or
    both sides of a pair), where a single ``IN (...)`` would be wrong: each dataset
    has a different sample allow-list. A row passes if it belongs to a dataset
    *without* a filter, or its sample is in that dataset's allow-list, so unfiltered
    datasets are untouched. A filtered dataset whose allow-list is empty contributes
    no rows.

    :param conn: Read-only DuckDB connection.
    :param db_names: Datasets that appear in the query.
    :param filters: Per-dataset filter specs keyed by db_name (variants already
        expanded -- see :func:`expand_filters_to_variants`).
    :param db_column: SQL expression yielding the row's dataset db_name.
    :param sample_column: SQL expression yielding the row's sample id.
    :returns: ``(sql_fragment, params)``, each condition prefixed ``AND``; empty when no
        listed dataset has a filter.

    """
    parts: list[str] = []
    params: list = []
    for db in dict.fromkeys(db_names):
        spec = filters.get(db)
        if not spec:
            continue
        ids = get_filtered_sample_ids(conn, db, spec)
        if not ids:
            parts.append(f" AND {db_column} <> ?")
            params.append(db)
            continue
        placeholders = ", ".join(["?"] * len(ids))
        passes = f"{db_column} <> ? OR {sample_column} IN ({placeholders})"
        parts.append(f" AND ({passes})")
        params.append(db)
        params.extend(ids)
    return "".join(parts), params


__all__ = [
    "expand_filters_to_variants",
    "fetch_corr_pairs",
    "get_filtered_sample_ids",
    "per_dataset_sample_clause",
    "sample_filter_clause",
    "sample_in_clause",
]
