"""
Fingerprint every table of a materialized DuckDB file.

Writes ``{table: {"rows": n, "columns": [...], "md5": hash}}`` as JSON. The hash is
order-independent: each row is rendered as JSON and the rows are sorted before hashing,
so two databases with the same content but different physical row order fingerprint
identically. Pair with ``diff_snapshots.py`` to compare a rebuild against a baseline.

Usage::

    poetry run python scripts/snapshot_db.py brentlab_yeast.duckdb out.json
    poetry run python scripts/snapshot_db.py db.duckdb out.json \
        --columns topn_results=a,b,c

``--columns TABLE=col1,col2`` restricts the fingerprint of TABLE to those columns
(repeatable), for comparing a table whose schema gained columns against a baseline that
lacks them.

"""

from __future__ import annotations

import argparse
import json
import sys

import duckdb


def fingerprint_table(
    conn: duckdb.DuckDBPyConnection, table: str, columns: list[str] | None = None
) -> dict:
    """
    Row count, column list and an order-independent md5 of one table.

    :param conn: Open connection.
    :param table: Table name.
    :param columns: Optional subset of columns to hash; ``None`` hashes every column.
    :returns: ``{"rows": int, "columns": [...], "md5": str}``.

    """
    all_columns = [r[0] for r in conn.execute(f'DESCRIBE "{table}"').fetchall()]
    use = columns or all_columns
    missing = [c for c in use if c not in all_columns]
    if missing:
        raise SystemExit(f"{table}: no such column(s) {missing}")
    projection = ", ".join(f'"{c}"' for c in use)
    rows, md5 = conn.execute(
        f"""
        SELECT count(*),
               md5(string_agg(to_json(t)::VARCHAR, chr(10)
                              ORDER BY to_json(t)::VARCHAR))
        FROM (SELECT {projection} FROM "{table}") t
        """
    ).fetchone()
    return {"rows": int(rows), "columns": use, "md5": md5 or ""}


def snapshot(db_path: str, columns_by_table: dict[str, list[str]]) -> dict:
    """
    Fingerprint every table in ``db_path``.

    :param db_path: Path to the DuckDB file (opened read-only).
    :param columns_by_table: Per-table column subsets, from ``--columns``.
    :returns: ``{table: fingerprint}`` sorted by table name.

    """
    conn = duckdb.connect(db_path, read_only=True)
    try:
        tables = sorted(r[0] for r in conn.execute("SHOW TABLES").fetchall())
        return {t: fingerprint_table(conn, t, columns_by_table.get(t)) for t in tables}
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("db_path")
    parser.add_argument("out_json")
    parser.add_argument(
        "--columns",
        action="append",
        default=[],
        metavar="TABLE=col1,col2",
        help="Hash only these columns of TABLE (repeatable).",
    )
    args = parser.parse_args(argv)
    columns_by_table: dict[str, list[str]] = {}
    for spec in args.columns:
        table, _, cols = spec.partition("=")
        if not cols:
            parser.error(f"--columns needs TABLE=col1,col2, got {spec!r}")
        columns_by_table[table] = [c.strip() for c in cols.split(",")]
    result = snapshot(args.db_path, columns_by_table)
    with open(args.out_json, "w") as fh:
        json.dump(result, fh, indent=2, sort_keys=True)
    for table, fp in result.items():
        print(f"{table:42s} {fp['rows']:>10,}  {fp['md5'][:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
