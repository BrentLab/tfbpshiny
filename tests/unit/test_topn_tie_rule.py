"""
The top-N membership rule for binding scores, and the no-signal value.

``"rank"`` is ``RANK() <= N``: a tie group is in when its first member's rank is
within N. ``"avg_rank"`` keeps a tie group only when its *average*
rank is within N, so a large group straddling the cutoff drops out whole, and a group
kept whole can push ``n`` above N. A NULL score ("reported, no signal") ranks as
``no_signal_value`` and forms one tie group at the bottom, which never qualifies unless
the pool is tiny.

"""

from __future__ import annotations

from collections.abc import Sequence

import duckdb
import pandas as pd
import pytest

from tests.unit._topn_oracle import topn_pair_select_sql
from tfbpshiny.materialize.comparison.topn import (
    binding_stage_sql,
    perturbation_stage_sql,
    topn_pair_select_sql_v2,
)

B = ("BrentLab/fake_binding", "cfg_b")
P = ("BrentLab/fake_pert", "cfg_p")


def _conn(scores: Sequence[float | None]) -> duckdb.DuckDBPyConnection:
    """
    One regulator, one binding sample; target ``Ti`` has score ``scores[i]``.

    Every target is measured (and responsive) in the perturbation data, so the pool is
    the whole list.

    """
    conn = duckdb.connect()
    conn.execute(
        "CREATE TABLE fake_binding (sample_id INTEGER, regulator_locus_tag VARCHAR,"
        " target_locus_tag VARCHAR, max_score DOUBLE)"
    )
    conn.executemany(
        "INSERT INTO fake_binding VALUES (1, 'REG', ?, ?)",
        [(f"T{i}", s) for i, s in enumerate(scores)],
    )
    conn.execute(
        "CREATE TABLE kemmeren (sample_id INTEGER, regulator_locus_tag VARCHAR,"
        ' target_locus_tag VARCHAR, "Madj" DOUBLE, pval DOUBLE)'
    )
    conn.executemany(
        "INSERT INTO kemmeren VALUES (7, 'REG', ?, 3.0, 0.001)",
        [(f"T{i}",) for i in range(len(scores))],
    )
    return conn


def _staged(
    conn: duckdb.DuckDBPyConnection,
    top_n: int,
    tie_rule: str,
    no_signal_value: float | None = None,
) -> pd.DataFrame:
    b_sql, b_params = binding_stage_sql(
        "fake_binding",
        "sample_id",
        "max_score",
        (),
        "",
        no_signal_value=no_signal_value,
    )
    conn.execute(f"CREATE OR REPLACE TABLE _b AS {b_sql}", b_params)
    p_sql, p_params = perturbation_stage_sql("kemmeren")
    conn.execute(f"CREATE OR REPLACE TABLE _p AS {p_sql}", p_params)
    sql, params = topn_pair_select_sql_v2(
        binding_db="fake_binding",
        perturbation_db="kemmeren",
        binding_table="_b",
        binding_hf_repo=B[0],
        binding_hf_config=B[1],
        perturbation_table="_p",
        pert_hf_repo=P[0],
        pert_hf_config=P[1],
        rank_col="max_score",
        rank_asc=False,
        top_n_values=(top_n,),
        threshold_pairs=((0.0, 0.05),),
        has_pvalue=True,
        tie_rule=tie_rule,
    )
    return conn.execute(sql, params).df()


def _oracle(
    conn: duckdb.DuckDBPyConnection,
    top_n: int,
    tie_rule: str,
    no_signal_value: float | None = None,
) -> pd.DataFrame:
    sql, params = topn_pair_select_sql(
        binding_view="fake_binding",
        binding_hf_repo=B[0],
        binding_hf_config=B[1],
        perturbation_view="kemmeren",
        pert_hf_repo=P[0],
        pert_hf_config=P[1],
        binding_sample_col="sample_id",
        rank_col="max_score",
        rank_asc=False,
        target_blacklist=(),
        binding_dedup_cte="",
        top_n=top_n,
        effect_threshold=0.0,
        pvalue_threshold=0.05,
        tie_rule=tie_rule,
        no_signal_value=no_signal_value,
    )
    return conn.execute(sql, params).df()


def _n(df: pd.DataFrame) -> int | None:
    """``n`` for the single row, or ``None`` when the list is empty (no row at all)."""
    return None if df.empty else int(df["n"].iloc[0])


# (scores, top_n, n under "rank", n under "avg_rank")
CASES = {
    "distinct scores": ([9, 8, 7, 6, 5, 4, 3, 2], 5, 5, 5),
    "tie group ends exactly at N": ([9, 8, 7, 5, 5, 1], 5, 5, 5),
    # ranks 5-9, average 7 > 5: kept whole by RANK, dropped by the average-rank rule.
    "group straddles the cutoff, average > N": (
        [9, 8, 7, 6, 5, 5, 5, 5, 5, 1],
        5,
        9,
        4,
    ),
    # ranks 3-6, average 4.5 <= 5: kept whole, so n exceeds N.
    "group straddles the cutoff, average <= N": ([9, 8, 5, 5, 5, 5, 1], 5, 6, 6),
    # nine tied at the top: ranks 1-9, average exactly 5 -> kept whole (2N-1).
    "2N-1 tied at the top": ([4] * 9 + [1], 5, 9, 9),
    # ten tied at the top: ranks 1-10, average 5.5 > 5 -> dropped, nothing left.
    "2N tied at the top": ([4] * 10 + [1], 5, 10, None),
}


@pytest.mark.parametrize("name", list(CASES))
def test_membership_under_each_rule(name: str) -> None:
    scores, top_n, want_rank, want_avg = CASES[name]
    conn = _conn(scores)
    assert _n(_staged(conn, top_n, "rank")) == want_rank
    assert _n(_staged(conn, top_n, "avg_rank")) == want_avg


@pytest.mark.parametrize("name", list(CASES))
@pytest.mark.parametrize("rule", ["rank", "avg_rank"])
def test_the_two_builders_agree_under_either_rule(name: str, rule: str) -> None:
    scores, top_n, *_ = CASES[name]
    conn = _conn(scores)
    assert _n(_oracle(conn, top_n, rule)) == _n(_staged(conn, top_n, rule))


def test_a_group_kept_whole_can_exceed_n_but_a_dropped_one_leaves_it_short() -> None:
    kept = _staged(_conn([9, 8, 5, 5, 5, 5, 1]), 5, "avg_rank")
    short = _staged(_conn([9, 8, 7, 6, 5, 5, 5, 5, 5, 1]), 5, "avg_rank")
    assert int(kept["n"].iloc[0]) > 5
    assert int(short["n"].iloc[0]) < 5


# --- the no-signal group -------------------------------------------------------------


def test_the_no_signal_group_is_dropped_when_the_pool_is_large() -> None:
    """Three peaks and a hundred no-peak promoters: the NULLs are one tie group at ranks
    4-103 (average 53), so only the three peaks are in the top 5."""
    conn = _conn([9.0, 8.0, 7.0] + [None] * 100)
    out = _staged(conn, 5, "avg_rank", no_signal_value=0.0)
    assert _n(out) == 3
    # The pool still includes every reported promoter -- that is what "report all
    # promoters" buys -- so the full-overlap floor is judged on n, not on this.
    assert int(out["n_intersecting_targets"].iloc[0]) == 103


def test_the_rank_rule_sweeps_the_whole_no_signal_group_in() -> None:
    """Why the default is ``avg_rank``: with fewer than N peaks, RANK() lets the whole
    no-peak group in, so n is the size of the pool, not a top-N."""
    conn = _conn([9.0, 8.0, 7.0] + [None] * 100)
    assert _n(_staged(conn, 5, "rank", no_signal_value=0.0)) == 103


def test_the_no_signal_group_can_qualify_when_the_pool_is_tiny() -> None:
    """Average rank (3+5)/2 = 4 <= 5: with only five promoters there is nothing else."""
    conn = _conn([9.0, 8.0, None, None, None])
    assert _n(_staged(conn, 5, "avg_rank", no_signal_value=0.0)) == 5


def test_null_score_ranks_as_the_no_signal_value_not_by_session_ordering() -> None:
    """A NULL must rank below every real score whether or not the session happens to put
    NULLs last; the no-signal value makes that explicit."""
    conn = _conn([9.0, 8.0, 7.0] + [None] * 100)
    b_sql, b_params = binding_stage_sql(
        "fake_binding", "sample_id", "max_score", (), "", no_signal_value=0.0
    )
    conn.execute("SET default_null_order = 'NULLS_FIRST'")
    conn.execute(f"CREATE OR REPLACE TABLE _b AS {b_sql}", b_params)
    values = conn.execute("SELECT DISTINCT rank_value FROM _b ORDER BY 1").fetchall()
    assert [v[0] for v in values] == [0.0, 7.0, 8.0, 9.0]
    assert _n(_staged(conn, 5, "avg_rank", no_signal_value=0.0)) == 3


def test_a_real_score_never_ties_with_the_no_signal_value() -> None:
    """Peak scores are >= 1 (Rossi) and >= 89 (ChEC-seq), so 0 is strictly below
    them."""
    conn = _conn([1.0, 1.0, None, None])
    out = _staged(conn, 2, "avg_rank", no_signal_value=0.0)
    assert (
        _n(out) == 2
    )  # the two real peaks tie at ranks 1-2 (average 1.5); NULLs excluded


def test_an_unknown_tie_rule_is_rejected() -> None:
    conn = _conn([1.0])
    with pytest.raises(ValueError, match="tie_rule"):
        _staged(conn, 5, "median_rank")
