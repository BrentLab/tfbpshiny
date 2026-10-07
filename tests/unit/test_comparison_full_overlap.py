"""
"Require full overlap" on the Comparison tab keeps a (regulator, sample pair) only when
its top-N list is complete after the tie rule: ``n >= top_n``. ``n`` counts the targets
that passed the rule, so a regulator with too few scored targets -- or a large tie group
around rank N that the average-rank rule excluded -- is removed. The old test,
``n_intersecting_targets >= top_n`` (pool size), is vacuous once peak-calling tables
report every promoter.
"""

from __future__ import annotations

import duckdb

from tfbpshiny.modules.comparison.queries import fetch_topn_results


def _conn() -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect()
    conn.execute(
        "CREATE TABLE dataset_registry (db_name VARCHAR, hf_repo VARCHAR,"
        " hf_config VARCHAR)"
    )
    conn.execute(
        "INSERT INTO dataset_registry VALUES ('b', 'R', 'cb'), ('p', 'R', 'cp')"
    )
    for db in ("b", "p"):
        conn.execute(f'CREATE TABLE "{db}_meta" (sample_id VARCHAR)')
        conn.execute(f"INSERT INTO \"{db}_meta\" VALUES ('s')")
    conn.execute(
        "CREATE TABLE topn_results (binding_source_sample VARCHAR,"
        " perturbation_source_sample VARCHAR, regulator_locus_tag VARCHAR,"
        " top_n INTEGER, effect_threshold DOUBLE, pvalue_threshold DOUBLE,"
        " n INTEGER, n_responsive INTEGER, responsive_ratio DOUBLE,"
        " n_intersecting_targets INTEGER)"
    )
    # Every pool is huge (dense peak data), so the pool-size test would keep them all.
    rows = [
        ("FULL", 25),  # complete list
        ("OVER", 31),  # a tie group kept whole: longer than N is still complete
        ("SHORT", 19),  # a tie group around rank N was excluded
        ("FEWPEAKS", 3),  # fewer than N scored targets
    ]
    conn.executemany(
        "INSERT INTO topn_results VALUES ('R;cb;s', 'R;cp;s', ?, 25, 0.0, 0.05, ?, 1,"
        " 0.5, 4971)",
        rows,
    )
    return conn


def _regs(**kw) -> set[str]:
    df = fetch_topn_results(_conn(), [("b", "p")], {}, 25, {"*": (0.0, 0.05)}, **kw)
    return set(df["regulator_locus_tag"])


def test_the_floor_removes_short_lists() -> None:
    assert _regs(require_full_overlap=True) == {"FULL", "OVER"}


def test_without_the_floor_short_lists_are_kept() -> None:
    assert _regs(require_full_overlap=False) == {"FULL", "OVER", "SHORT", "FEWPEAKS"}


def test_the_floor_is_on_by_default() -> None:
    assert _regs() == {"FULL", "OVER"}
