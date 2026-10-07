"""
Figure 6 / 10 rank with ``ROW_NUMBER`` for exactly-N sets.

The recalled peak-calling datasets now report every promoter, with a NULL score where
there was no peak. Ranking those rows would pad a regulator that has fewer than N peaks
up to exactly N with no-peak promoters in alphabetical order, so the overlap would
measure nothing.

"""

from __future__ import annotations

import duckdb
import pandas as pd

from tfbpshiny.materialize.comparison.agreement import agreement_pair_select_sql


def _conn() -> duckdb.DuckDBPyConnection:
    """Two datasets for regulator R: ``peaks_a`` / ``peaks_b`` each have 3 scored
    targets (T0-T2) and 20 NULL-score targets, in the same sample 1."""
    conn = duckdb.connect()
    for view in ("peaks_a", "peaks_b"):
        conn.execute(
            f"CREATE TABLE {view} (sample_id INTEGER, regulator_locus_tag VARCHAR,"
            " target_locus_tag VARCHAR, max_score DOUBLE)"
        )
        rows: list[tuple[int, str, str, float | None]] = [
            (1, "R", f"T{i}", float(10 - i)) for i in range(3)
        ]
        rows += [(1, "R", f"U{i:02d}", None) for i in range(20)]
        conn.executemany(f"INSERT INTO {view} VALUES (?, ?, ?, ?)", rows)
    return conn


def _run(conn, **kw) -> pd.DataFrame:
    sql, params = agreement_pair_select_sql(
        view_a="peaks_a",
        hf_repo_a="R",
        hf_config_a="a",
        sample_col_a="sample_id",
        rank_col_a="max_score",
        rank_asc_a=False,
        view_b="peaks_b",
        hf_repo_b="R",
        hf_config_b="b",
        sample_col_b="sample_id",
        rank_col_b="max_score",
        rank_asc_b=False,
        comparison_type="binding",
        top_n_values=(10,),
        **kw,
    )
    return conn.execute(sql, params).df()


def test_without_the_flag_a_regulator_is_padded_to_n_with_no_peak_promoters() -> None:
    out = _run(_conn())
    assert int(out["n_a"].iloc[0]) == 10  # 3 peaks + 7 alphabetical NULL-score fillers
    assert int(out["n_intersect"].iloc[0]) == 10  # identical fillers: fake agreement


def test_with_the_flag_only_scored_rows_are_ranked() -> None:
    out = _run(_conn(), drop_null_scores_a=True, drop_null_scores_b=True)
    assert int(out["n_a"].iloc[0]) == 3
    assert int(out["n_b"].iloc[0]) == 3
    assert int(out["n_intersect"].iloc[0]) == 3


def test_the_flag_applies_per_side() -> None:
    out = _run(_conn(), drop_null_scores_a=True)
    assert int(out["n_a"].iloc[0]) == 3
    assert int(out["n_b"].iloc[0]) == 10


def test_ties_among_scored_rows_break_by_target_locus_tag() -> None:
    """Stable membership: equal scores fall in target_locus_tag order on every build."""
    conn = duckdb.connect()
    for view in ("peaks_a", "peaks_b"):
        conn.execute(
            f"CREATE TABLE {view} (sample_id INTEGER, regulator_locus_tag VARCHAR,"
            " target_locus_tag VARCHAR, max_score DOUBLE)"
        )
        conn.executemany(
            f"INSERT INTO {view} VALUES (1, 'R', ?, 5.0)",
            [("T3",), ("T1",), ("T2",), ("T0",)],
        )
    sql, params = agreement_pair_select_sql(
        view_a="peaks_a",
        hf_repo_a="R",
        hf_config_a="a",
        sample_col_a="sample_id",
        rank_col_a="max_score",
        rank_asc_a=False,
        view_b="peaks_b",
        hf_repo_b="R",
        hf_config_b="b",
        sample_col_b="sample_id",
        rank_col_b="max_score",
        rank_asc_b=False,
        comparison_type="binding",
        top_n_values=(2,),
    )
    out = conn.execute(sql, params).df()
    # Both sides pick {T0, T1} (alphabetical among the four tied) so they fully overlap.
    assert int(out["n_a"].iloc[0]) == 2
    assert int(out["n_intersect"].iloc[0]) == 2
