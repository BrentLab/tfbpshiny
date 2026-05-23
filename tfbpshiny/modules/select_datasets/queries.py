"""SQL query helpers for the Select Datasets module."""

from __future__ import annotations

from typing import Any


def _build_where(
    filters: dict[str, Any] | None,
    params: dict[str, Any],
    prefix: str = "",
) -> str:
    """
    Build a WHERE clause string and populate ``params`` in-place.

    :param filters: Filter spec — ``{field: {"type": ..., "value": ...}}``.
    :param params: Dict to populate with bound parameter values.
    :param prefix: String prepended to every param name to avoid collisions
        when two datasets share the same field names in one query.
    :return: WHERE clause string (empty string if no filters).

    """
    clauses: list[str] = []

    for field, spec in (filters or {}).items():
        kind = spec["type"]
        val = spec["value"]
        p = (f"{prefix}{field}" if prefix else field).replace(" ", "_")

        if kind == "categorical":
            clauses.append(f'"{field}" = ANY($cat_{p})')
            params[f"cat_{p}"] = val
        elif kind == "numeric":
            lo, hi = val
            clauses.append(f'"{field}" BETWEEN $num_{p}_lo AND $num_{p}_hi')
            params[f"num_{p}_lo"] = lo
            params[f"num_{p}_hi"] = hi
        elif kind == "bool":
            clauses.append(f'"{field}" = $bool_{p}')
            params[f"bool_{p}"] = bool(val)

    return f" WHERE {' AND '.join(clauses)}" if clauses else ""


def metadata_query(
    db_name: str, filters: dict[str, Any] | None = None
) -> tuple[str, dict[str, Any]]:
    """
    Return ``(sql, params)`` for querying the dataset's meta view with optional filters.

    :param db_name: Dataset name (e.g. ``'harbison'``).
    :param filters: Active filters for this dataset — the ``filter_dict[db_name]``
        value. Structure:
        ``{field: {"type": "categorical"|"numeric"|"bool", "value": ...}}``.
    :return: ``(sql_string, params_dict)`` ready for ``vdb.query(sql, **params)``.

    """
    params: dict[str, Any] = {}
    where = _build_where(filters, params)
    return f"SELECT * FROM {db_name}_meta{where}", params


def sample_count_query(
    db_name: str,
    filters: dict[str, Any] | None = None,
    restrict_to_regulators: list[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Return ``(sql, params)`` for counting samples in a dataset's meta view.

    :param db_name: Dataset name.
    :param filters: Active filters for this dataset.
    :param restrict_to_regulators: If provided, only count rows whose
        ``regulator_locus_tag`` is in this list.
    :return: ``(sql_string, params_dict)`` — query returns one row with column ``n``.

    """
    params: dict[str, Any] = {}
    where = _build_where(filters, params)

    if restrict_to_regulators:
        placeholders = ", ".join(
            f"$reg_{db_name}_{i}" for i in range(len(restrict_to_regulators))
        )
        reg_clause = f"regulator_locus_tag IN ({placeholders})"
        for i, v in enumerate(restrict_to_regulators):
            params[f"reg_{db_name}_{i}"] = v
        where = f"{where} AND {reg_clause}" if where else f" WHERE {reg_clause}"

    return f"SELECT COUNT(sample_id) AS n FROM {db_name}_meta{where}", params


def regulator_locus_tags_query(
    db_name: str,
    filters: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Return ``(sql, params)`` for fetching distinct regulator locus tags.

    :param db_name: Dataset name.
    :param filters: Active filters for this dataset.
    :return: ``(sql_string, params_dict)`` — query returns rows with column
        ``regulator_locus_tag``.

    """
    params: dict[str, Any] = {}
    where = _build_where(filters, params)
    return (
        f"SELECT DISTINCT regulator_locus_tag FROM {db_name}_meta{where}",
        params,
    )


def regulator_breakdown_query(
    db_name: str,
    candidate_cols: list[str],
    filters: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Return ``(sql, params)`` for a single query that counts multi-sample regulators and
    distinct values per candidate column in one pass.

    The result is a single row with:

    - ``n_multi`` — number of regulators that appear in more than one sample
    - One column per entry in ``candidate_cols`` — the number of distinct
      values for that column across multi-sample regulators only

    If ``n_multi`` is 0 every regulator maps to exactly one sample (uniform).
    Otherwise, candidate columns where the count is > 1 are the differentiating
    columns.

    :param db_name: Dataset name.
    :param candidate_cols: Columns to check, pre-filtered to exclude identity
        and hidden fields.
    :param filters: Active filters for this dataset.
    :return: ``(sql_string, params_dict)``.

    """
    params: dict[str, Any] = {}
    where = _build_where(filters, params)
    # per_reg: one scan — count samples per regulator, count distinct values per
    # candidate col; HAVING filters to multi-sample regulators only.
    per_reg_exprs = ", ".join(f'COUNT(DISTINCT "{c}") AS "{c}"' for c in candidate_cols)
    # agg: for each candidate col, count regulators where the distinct-value count > 1.
    agg_exprs = ", ".join(
        f'COUNT(*) FILTER (WHERE "{c}" > 1) AS "{c}"' for c in candidate_cols
    )
    per_reg_select = (
        f"SELECT regulator_locus_tag"
        + (f", {per_reg_exprs}" if per_reg_exprs else "")
        + f" FROM {db_name}_meta{where}"
        + " GROUP BY regulator_locus_tag"
        + " HAVING COUNT(*) > 1"
    )
    sql = (
        f"WITH per_reg AS ({per_reg_select})"
        " SELECT COUNT(*) AS n_multi"
        + (f", {agg_exprs}" if agg_exprs else "")
        + " FROM per_reg"
    )
    return sql, params


def regulator_display_labels_query(db_name: str) -> tuple[str, dict]:
    """
    Return ``(sql, params)`` for fetching distinct regulator locus tags and symbols.

    Used to build the ``{locus_tag: "SYMBOL (LOCUS_TAG)"}`` display map for the
    Regulator selectize in the filter modal.

    :param db_name: Dataset name.
    :return: ``(sql_string, params_dict)`` — rows have columns
        ``regulator_locus_tag`` and ``regulator_symbol``.

    """
    return (
        f"SELECT DISTINCT regulator_locus_tag, regulator_symbol"
        f" FROM {db_name}_meta"
        f" ORDER BY regulator_locus_tag",
        {},
    )


def matrix_diagonal_query(
    active: list[str],
    filters: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """
    Return ``(sql, params)`` for counting distinct regulators and samples for every
    active dataset in a single UNION ALL query.

    Result columns: ``db_name`` (str), ``n_regulators`` (int), ``n_samples`` (int).

    :param active: Ordered list of active dataset names.
    :param filters: Active filter dict keyed by dataset name.
    :return: ``(sql_string, params_dict)``.

    """
    params: dict[str, Any] = {}
    parts: list[str] = []
    for db_name in active:
        db_filters = filters.get(db_name)
        prefix = f"diag_{db_name}_"
        where = _build_where(db_filters, params, prefix=prefix)
        parts.append(
            f"SELECT '{db_name}' AS db_name,"
            f" COUNT(DISTINCT regulator_locus_tag) AS n_regulators,"
            f" COUNT(DISTINCT sample_id) AS n_samples"
            f" FROM {db_name}_meta{where}"
        )
    sql = "\nUNION ALL\n".join(parts)
    return sql, params


def matrix_cross_dataset_query(
    pairs: list[tuple[str, str]],
    filters: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """
    Return ``(sql, params)`` for counting common regulators and restricted sample counts
    for every (db_a, db_b) pair in a single UNION ALL query.

    Result columns: ``pair_id`` (str, ``"{db_a}__{db_b}"``), ``n_common`` (int),
    ``samples_a`` (int), ``samples_b`` (int).

    The common-regulator set is computed in SQL via INTERSECT so no Python-side
    set operations are required. Each pair contributes one row.

    :param pairs: List of ``(db_a, db_b)`` tuples.
    :param filters: Active filter dict keyed by dataset name.
    :return: ``(sql_string, params_dict)``.

    """
    params: dict[str, Any] = {}
    parts: list[str] = []
    for db_a, db_b in pairs:
        pair_id = f"{db_a}__{db_b}"
        fa = filters.get(db_a)
        fb = filters.get(db_b)
        # INTERSECT arms: use distinct prefixes for each arm's WHERE params.
        prefix_a = f"cross_{pair_id}_{db_a}_"
        prefix_b = f"cross_{pair_id}_{db_b}_"
        where_a = _build_where(fa, params, prefix=prefix_a)
        where_b = _build_where(fb, params, prefix=prefix_b)
        # Sample-count arms need their own WHERE params (different prefix).
        prefix_sa = f"cs_{pair_id}_{db_a}_"
        prefix_sb = f"cs_{pair_id}_{db_b}_"
        where_sa = _build_where(fa, params, prefix=prefix_sa)
        where_sb = _build_where(fb, params, prefix=prefix_sb)
        and_common_a = (
            f"{' AND ' if where_sa else ' WHERE '}"
            "regulator_locus_tag IN (SELECT regulator_locus_tag FROM common)"
        )
        and_common_b = (
            f"{' AND ' if where_sb else ' WHERE '}"
            "regulator_locus_tag IN (SELECT regulator_locus_tag FROM common)"
        )
        # Wrap in an inline CTE so the INTERSECT is materialised once and
        # referenced three times (n_common, samples_a, samples_b).
        parts.append(
            f"SELECT * FROM ("
            f" WITH common AS ("
            f"  SELECT regulator_locus_tag FROM {db_a}_meta{where_a}"
            f"  INTERSECT"
            f"  SELECT regulator_locus_tag FROM {db_b}_meta{where_b}"
            f" )"
            f" SELECT '{pair_id}' AS pair_id,"
            f"  (SELECT COUNT(*) FROM common) AS n_common,"
            f"  (SELECT COUNT(DISTINCT sample_id)"
            f"   FROM {db_a}_meta{where_sa}{and_common_a}) AS samples_a,"
            f"  (SELECT COUNT(DISTINCT sample_id)"
            f"   FROM {db_b}_meta{where_sb}{and_common_b}) AS samples_b"
            f")"
        )
    if not parts:
        return (
            "SELECT NULL AS pair_id, 0 AS n_common, 0 AS samples_a, 0 AS samples_b WHERE FALSE",
            {},
        )
    sql = "\nUNION ALL\n".join(parts)
    return sql, params


def regulator_intersection_query(
    db_a: str,
    db_b: str,
    filters_a: dict[str, Any] | None,
    filters_b: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    """
    Return ``(sql, params)`` for the sorted list of regulator locus tags shared between
    ``db_a`` and ``db_b``, subject to their respective filters.

    The caller is responsible for excluding any existing ``regulator_locus_tag``
    filter from both filter dicts before calling this function, so that the
    intersection is computed from the full regulator set for each dataset
    (subject to other active filters only).

    :param db_a: First dataset name.
    :param db_b: Second dataset name.
    :param filters_a: Active filters for ``db_a`` (without ``regulator_locus_tag``).
    :param filters_b: Active filters for ``db_b`` (without ``regulator_locus_tag``).
    :returns: ``(sql_string, params_dict)`` — query returns rows with column
        ``regulator_locus_tag``, ordered ascending.

    """
    params: dict[str, Any] = {}
    where_a = _build_where(filters_a, params, prefix=f"ri_{db_a}_")
    where_b = _build_where(filters_b, params, prefix=f"ri_{db_b}_")
    sql = (
        f"SELECT regulator_locus_tag FROM {db_a}_meta{where_a}"
        f" INTERSECT"
        f" SELECT regulator_locus_tag FROM {db_b}_meta{where_b}"
        f" ORDER BY regulator_locus_tag"
    )
    return sql, params


def full_data_query(
    db_name: str, filters: dict[str, Any] | None = None
) -> tuple[str, dict[str, Any]]:
    """
    Return ``(sql, params)`` for querying the dataset's full data view with optional
    filters.

    The full data view (``{db_name}``) includes all genomic data columns joined with
    metadata columns.

    :param db_name: Dataset name (e.g. ``'harbison'``).
    :param filters: Active filters for this dataset — same structure as
        :func:`metadata_query`.
    :return: ``(sql_string, params_dict)`` ready for ``vdb.query(sql, **params)``.

    """
    params: dict[str, Any] = {}
    where = _build_where(filters, params)
    return f"SELECT * FROM {db_name}{where}", params


__all__ = [
    "metadata_query",
    "full_data_query",
    "matrix_diagonal_query",
    "matrix_cross_dataset_query",
    "sample_count_query",
    "regulator_locus_tags_query",
    "regulator_breakdown_query",
    "regulator_display_labels_query",
    "regulator_intersection_query",
]
