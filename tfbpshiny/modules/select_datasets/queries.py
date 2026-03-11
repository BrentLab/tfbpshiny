"""SQL query helpers for the Select Datasets module."""

from __future__ import annotations

from typing import Any


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
    clauses: list[str] = []
    params: dict[str, Any] = {}

    for field, spec in (filters or {}).items():
        kind = spec["type"]
        val = spec["value"]
        if kind == "categorical":
            placeholders = ", ".join(f"$cat_{field}_{i}" for i in range(len(val)))
            clauses.append(f"{field} IN ({placeholders})")
            for i, v in enumerate(val):
                params[f"cat_{field}_{i}"] = v
        elif kind == "numeric":
            lo, hi = val
            clauses.append(f"{field} BETWEEN $num_{field}_lo AND $num_{field}_hi")
            params[f"num_{field}_lo"] = lo
            params[f"num_{field}_hi"] = hi
        elif kind == "bool":
            clauses.append(f"{field} = $bool_{field}")
            params[f"bool_{field}"] = bool(val)

    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM {db_name}_meta{where}"
    return sql, params


__all__ = ["metadata_query"]
