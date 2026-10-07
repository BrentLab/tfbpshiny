"""
Figure 10's target lists must rank only scored rows on dense peak datasets.

The recalled peak-calling datasets report every promoter, with a NULL score where no
peak qualified. Without ``drop_null_scores`` a regulator with three peaks would have its
"top 10" padded with seven no-peak promoters in alphabetical order, exactly the padding
``agreement.py`` guards against with ``drop_null_scores_a/b``.

"""

from __future__ import annotations

import duckdb
import pandas as pd

from tfbpshiny.materialize.comparison.target_sets import target_sets_select_sql


def _conn() -> duckdb.DuckDBPyConnection:
    """Regulator R in sample 1: 3 scored targets (T0-T2) and 20 NULL-score targets."""
    conn = duckdb.connect()
    conn.execute(
        "CREATE TABLE peaks (sample_id INTEGER, regulator_locus_tag VARCHAR,"
        " target_locus_tag VARCHAR, max_score DOUBLE)"
    )
    rows: list[tuple[int, str, str, float | None]] = [
        (1, "R", f"T{i}", float(10 - i)) for i in range(3)
    ]
    rows += [(1, "R", f"U{i:02d}", None) for i in range(20)]
    conn.executemany("INSERT INTO peaks VALUES (?, ?, ?, ?)", rows)
    return conn


def _run(conn: duckdb.DuckDBPyConnection, **kw) -> pd.DataFrame:
    sql = target_sets_select_sql(
        "peaks", "R", "a", "sample_id", "max_score", False, "binding", max_n=10, **kw
    )
    return conn.execute(sql).df()


def test_without_the_flag_no_peak_promoters_fill_the_list() -> None:
    out = _run(_conn())
    assert len(out) == 10
    assert set(out["target_locus_tag"]) >= {"T0", "T1", "T2"}
    assert out["target_locus_tag"].str.startswith("U").sum() == 7


def test_with_the_flag_only_scored_rows_are_ranked() -> None:
    out = _run(_conn(), drop_null_scores=True)
    assert sorted(out["target_locus_tag"]) == ["T0", "T1", "T2"]
    assert sorted(out["rnk"]) == [1, 2, 3]
