"""
The staged top-N SQL must produce exactly what the per-variant SQL produces.

`topn_pair_select_sql` runs once per (top_n, effect, pvalue) variant;
`topn_pair_select_sql_v2` emits every variant from one scan-and-rank. The two differ
only in performance, so any difference in the rows is a bug. These tests run both
against the same synthetic data and compare the result *sets*.

Row order is not compared -- the staged query groups differently and emits in a
different order -- but content and row count are.

"""

from __future__ import annotations

from typing import Any

import duckdb
import pandas as pd
import pytest

from tests.unit._topn_oracle import topn_pair_select_sql
from tfbpshiny.materialize.comparison.topn import (
    TOP_N_ALL,
    binding_stage_sql,
    perturbation_stage_sql,
    topn_pair_select_sql_v2,
)

B_REPO, B_CFG = "BrentLab/fake_binding", "cfg_b"
P_REPO, P_CFG = "BrentLab/fake_pert", "cfg_p"

#: Columns compared between the two paths, in a stable order.
COLS = [
    "binding_source_sample",
    "perturbation_source_sample",
    "regulator_locus_tag",
    "top_n",
    "rank_col",
    "rank_asc",
    "effect_threshold",
    "pvalue_threshold",
    "n",
    "n_responsive",
    "responsive_ratio",
    "n_intersecting_targets",
]


def _conn(
    binding_rows: list[tuple], pert_rows: list[tuple]
) -> duckdb.DuckDBPyConnection:
    """
    Build an in-memory database shaped like a kemmeren-style pair.

    Binding is ranked by ``enrichment`` descending; perturbation carries both an effect
    (``Madj``) and a p-value (``pval``), matching ``PERTURBATION_DATASET_COLUMNS``.

    """
    conn = duckdb.connect()
    conn.execute(
        "CREATE TABLE fake_binding (sample_id INTEGER, regulator_locus_tag VARCHAR,"
        " target_locus_tag VARCHAR, enrichment DOUBLE)"
    )
    conn.executemany("INSERT INTO fake_binding VALUES (?, ?, ?, ?)", binding_rows)
    conn.execute(
        "CREATE TABLE kemmeren (sample_id INTEGER, regulator_locus_tag VARCHAR,"
        ' target_locus_tag VARCHAR, "Madj" DOUBLE, pval DOUBLE)'
    )
    conn.executemany("INSERT INTO kemmeren VALUES (?, ?, ?, ?, ?)", pert_rows)
    return conn


def _oracle(
    conn: duckdb.DuckDBPyConnection,
    top_n_values: tuple[int, ...],
    pairs: tuple[tuple[float, float], ...],
    *,
    blacklist: tuple[str, ...] = (),
    regulators: tuple[str, ...] = (),
) -> pd.DataFrame:
    """Run the per-variant query once per combination and union the results."""
    frames = []
    for top_n in top_n_values:
        for eff, pval in pairs:
            sql, params = topn_pair_select_sql(
                binding_view="fake_binding",
                binding_hf_repo=B_REPO,
                binding_hf_config=B_CFG,
                perturbation_view="kemmeren",
                pert_hf_repo=P_REPO,
                pert_hf_config=P_CFG,
                binding_sample_col="sample_id",
                rank_col="enrichment",
                rank_asc=False,
                target_blacklist=blacklist,
                binding_dedup_cte="",
                top_n=top_n,
                effect_threshold=eff,
                pvalue_threshold=pval,
                regulator_subset=regulators,
            )
            frames.append(conn.execute(sql, params).df())
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _staged(
    conn: duckdb.DuckDBPyConnection,
    top_n_values: tuple[int, ...],
    pairs: tuple[tuple[float, float], ...],
    *,
    blacklist: tuple[str, ...] = (),
    regulators: tuple[str, ...] = (),
) -> pd.DataFrame:
    """Materialize stages A and B, then run stage C once."""
    b_sql, b_params = binding_stage_sql(
        binding_view="fake_binding",
        binding_sample_col="sample_id",
        rank_col="enrichment",
        target_blacklist=blacklist,
        binding_dedup_cte="",
    )
    conn.execute(f"CREATE OR REPLACE TABLE _mat_binding AS {b_sql}", b_params)
    p_sql, p_params = perturbation_stage_sql("kemmeren")
    conn.execute(f"CREATE OR REPLACE TABLE _mat_pert AS {p_sql}", p_params)

    sql, params = topn_pair_select_sql_v2(
        binding_db="fake_binding",
        perturbation_db="kemmeren",
        binding_table="_mat_binding",
        binding_hf_repo=B_REPO,
        binding_hf_config=B_CFG,
        perturbation_table="_mat_pert",
        pert_hf_repo=P_REPO,
        pert_hf_config=P_CFG,
        rank_col="enrichment",
        rank_asc=False,
        top_n_values=top_n_values,
        threshold_pairs=pairs,
        has_pvalue=True,
        regulator_subset=regulators,
    )
    return conn.execute(sql, params).df()


def _norm(df: pd.DataFrame) -> pd.DataFrame:
    """Sort rows and columns so two result sets can be compared directly."""
    if df.empty:
        return df
    out = df[COLS].copy()
    for c in ("responsive_ratio", "effect_threshold", "pvalue_threshold"):
        out[c] = out[c].round(12)
    return out.sort_values(COLS).reset_index(drop=True)


def _assert_same(oracle: pd.DataFrame, staged: pd.DataFrame) -> None:
    assert len(oracle) == len(staged), f"row count {len(oracle)} != {len(staged)}"
    pd.testing.assert_frame_equal(_norm(oracle), _norm(staged), check_dtype=False)


# --- fixtures ---------------------------------------------------------------------


def _plain_rows():
    """One regulator, eight targets, distinct scores; a second sample and regulator."""
    b = [(1, "REG1", f"T{i}", 100.0 - i) for i in range(8)]
    b += [(2, "REG1", f"T{i}", float(i)) for i in range(8)]
    b += [(1, "REG2", f"T{i}", 50.0 - i) for i in range(5)]
    p = [(7, "REG1", f"T{i}", 2.5 - 0.3 * i, 0.001 * (i + 1)) for i in range(8)]
    p += [(8, "REG1", f"T{i}", -3.0 + 0.5 * i, 0.02) for i in range(8)]
    p += [(7, "REG2", f"T{i}", 1.0, 0.04) for i in range(5)]
    return b, p


# --- tests ------------------------------------------------------------------------


def test_matches_on_the_ordinary_case() -> None:
    """Several cutoffs and two threshold pairs over well-separated scores."""
    conn = _conn(*_plain_rows())
    args = ((2, 3, 5), ((0.0, 0.05), (0.77, 0.05)))
    _assert_same(_oracle(conn, *args), _staged(conn, *args))


def test_matches_when_scores_tie_at_the_cutoff() -> None:
    """
    Ties at the rank boundary are where the cutoff join could silently diverge.

    `RANK()` gives tied rows the same rank, so `rnk <= 2` can return more than two
    targets and `n` exceeds `top_n`. The join must reproduce that, not truncate.

    """
    b = [(1, "REG1", f"T{i}", 10.0) for i in range(6)]  # all tied at rank 1
    b += [(1, "REG1", f"S{i}", 5.0) for i in range(3)]
    p = [(7, "REG1", f"T{i}", 2.0, 0.01) for i in range(6)]
    p += [(7, "REG1", f"S{i}", 0.1, 0.9) for i in range(3)]
    conn = _conn(b, p)
    args = ((1, 2, 5), ((0.0, 0.05),))
    oracle, staged = _oracle(conn, *args), _staged(conn, *args)
    # Guard the guard: the fixture must actually produce n > top_n.
    assert (oracle["n"] > oracle["top_n"]).any(), "fixture does not exercise ties"
    _assert_same(oracle, staged)


def test_matches_when_a_regulator_has_fewer_targets_than_top_n() -> None:
    """A cutoff larger than the candidate set must not invent rows."""
    conn = _conn(*_plain_rows())
    args = ((100,), ((0.0, 0.05),))
    _assert_same(_oracle(conn, *args), _staged(conn, *args))


def test_matches_for_the_all_targets_sentinel() -> None:
    """
    `TOP_N_ALL` means "no cutoff", not "cutoff zero".

    The staged query folds it into the cutoff join as `top_n = 0 OR rnk <= top_n`, so
    this asserts the sentinel still keeps every ranked row.

    """
    conn = _conn(*_plain_rows())
    args = ((TOP_N_ALL,), ((0.0, 0.05),))
    oracle, staged = _oracle(conn, *args), _staged(conn, *args)
    assert not staged.empty
    _assert_same(oracle, staged)


def test_matches_with_the_sentinel_alongside_real_cutoffs() -> None:
    """The sentinel and ordinary cutoffs are emitted from one query; both must hold."""
    conn = _conn(*_plain_rows())
    args = ((TOP_N_ALL, 2, 5), ((0.0, 0.05), (0.77, 0.1)))
    _assert_same(_oracle(conn, *args), _staged(conn, *args))


def test_matches_with_a_target_blacklist() -> None:
    """The blacklist is applied in stage A; it must still exclude before ranking."""
    conn = _conn(*_plain_rows())
    args = ((3,), ((0.0, 0.05),))
    kw: dict[str, Any] = {"blacklist": ("T0", "T1")}
    _assert_same(_oracle(conn, *args, **kw), _staged(conn, *args, **kw))


def test_matches_with_a_regulator_subset() -> None:
    """Batching by regulator must partition identically in both paths."""
    conn = _conn(*_plain_rows())
    args = ((3,), ((0.0, 0.05),))
    kw: dict[str, Any] = {"regulators": ("REG2",)}
    oracle, staged = _oracle(conn, *args, **kw), _staged(conn, *args, **kw)
    assert set(staged["regulator_locus_tag"]) == {"REG2"}
    _assert_same(oracle, staged)


def test_matches_when_effect_or_pvalue_is_null() -> None:
    """
    A NULL effect or p-value must count as not responsive, as it did before.

    `ABS(NULL) > x` is NULL, which the CASE sends to ELSE 0. Worth pinning: the staged
    query moved the comparison from the perturbation CTE into the aggregate.

    """
    b = [(1, "REG1", f"T{i}", 10.0 - i) for i in range(4)]
    p = [
        (7, "REG1", "T0", None, 0.01),
        (7, "REG1", "T1", 3.0, None),
        (7, "REG1", "T2", 3.0, 0.01),
        (7, "REG1", "T3", 0.1, 0.9),
    ]
    conn = _conn(b, p)
    args = ((4,), ((0.0, 0.05),))
    oracle, staged = _oracle(conn, *args), _staged(conn, *args)
    assert int(staged["n_responsive"].iloc[0]) == 1, "only T2 should be responsive"
    _assert_same(oracle, staged)


def test_no_pvalue_column_thresholds_on_effect_only() -> None:
    """
    Datasets without a p-value column threshold on effect alone.

    Stage B emits NULL for the missing column, so a staged query that forgot
    `has_pvalue=False` would compare against NULL and score everything zero. This pins
    the flag against the oracle's expression for `hackett`.

    """
    conn = duckdb.connect()
    conn.execute(
        "CREATE TABLE fake_binding (sample_id INTEGER, regulator_locus_tag VARCHAR,"
        " target_locus_tag VARCHAR, enrichment DOUBLE)"
    )
    conn.executemany(
        "INSERT INTO fake_binding VALUES (?, ?, ?, ?)",
        [(1, "REG1", f"T{i}", 10.0 - i) for i in range(4)],
    )
    conn.execute(
        "CREATE TABLE hackett (sample_id INTEGER, regulator_locus_tag VARCHAR,"
        " target_locus_tag VARCHAR, log2_shrunken_timecourses DOUBLE)"
    )
    conn.executemany(
        "INSERT INTO hackett VALUES (?, ?, ?, ?)",
        [(7, "REG1", f"T{i}", 2.0 - i) for i in range(4)],
    )

    sql, params = topn_pair_select_sql(
        binding_view="fake_binding",
        binding_hf_repo=B_REPO,
        binding_hf_config=B_CFG,
        perturbation_view="hackett",
        pert_hf_repo=P_REPO,
        pert_hf_config=P_CFG,
        binding_sample_col="sample_id",
        rank_col="enrichment",
        rank_asc=False,
        target_blacklist=(),
        binding_dedup_cte="",
        top_n=4,
        effect_threshold=0.5,
        pvalue_threshold=0.05,
    )
    oracle = conn.execute(sql, params).df()

    b_sql, b_params = binding_stage_sql(
        binding_view="fake_binding",
        binding_sample_col="sample_id",
        rank_col="enrichment",
        target_blacklist=(),
        binding_dedup_cte="",
    )
    conn.execute(f"CREATE OR REPLACE TABLE _mat_binding AS {b_sql}", b_params)
    p_sql, _ = perturbation_stage_sql("hackett")
    conn.execute(f"CREATE OR REPLACE TABLE _mat_pert AS {p_sql}")
    sql2, params2 = topn_pair_select_sql_v2(
        binding_db="fake_binding",
        perturbation_db="hackett",
        binding_table="_mat_binding",
        binding_hf_repo=B_REPO,
        binding_hf_config=B_CFG,
        perturbation_table="_mat_pert",
        pert_hf_repo=P_REPO,
        pert_hf_config=P_CFG,
        rank_col="enrichment",
        rank_asc=False,
        top_n_values=(4,),
        threshold_pairs=((0.5, 0.05),),
        has_pvalue=False,
    )
    staged = conn.execute(sql2, params2).df()
    assert int(oracle["n_responsive"].iloc[0]) > 0, "fixture scores nothing responsive"
    _assert_same(oracle, staged)


def test_ascending_rank_column_matches() -> None:
    """P-value-ranked datasets order the other way; the staged rank must follow."""
    b = [(1, "REG1", f"T{i}", 0.001 * (i + 1)) for i in range(6)]
    p = [(7, "REG1", f"T{i}", 2.0 - 0.4 * i, 0.01) for i in range(6)]
    conn = _conn(b, p)

    def oracle_asc():
        frames = []
        for top_n in (2, 4):
            sql, params = topn_pair_select_sql(
                binding_view="fake_binding",
                binding_hf_repo=B_REPO,
                binding_hf_config=B_CFG,
                perturbation_view="kemmeren",
                pert_hf_repo=P_REPO,
                pert_hf_config=P_CFG,
                binding_sample_col="sample_id",
                rank_col="enrichment",
                rank_asc=True,
                target_blacklist=(),
                binding_dedup_cte="",
                top_n=top_n,
                effect_threshold=0.0,
                pvalue_threshold=0.05,
            )
            frames.append(conn.execute(sql, params).df())
        return pd.concat(frames, ignore_index=True)

    b_sql, b_params = binding_stage_sql(
        "fake_binding", "sample_id", "enrichment", (), ""
    )
    conn.execute(f"CREATE OR REPLACE TABLE _mat_binding AS {b_sql}", b_params)
    p_sql, _ = perturbation_stage_sql("kemmeren")
    conn.execute(f"CREATE OR REPLACE TABLE _mat_pert AS {p_sql}")
    sql2, params2 = topn_pair_select_sql_v2(
        binding_db="fake_binding",
        perturbation_db="kemmeren",
        binding_table="_mat_binding",
        binding_hf_repo=B_REPO,
        binding_hf_config=B_CFG,
        perturbation_table="_mat_pert",
        pert_hf_repo=P_REPO,
        pert_hf_config=P_CFG,
        rank_col="enrichment",
        rank_asc=True,
        top_n_values=(2, 4),
        threshold_pairs=((0.0, 0.05),),
        has_pvalue=True,
    )
    _assert_same(oracle_asc(), conn.execute(sql2, params2).df())


def test_empty_variant_lists_are_rejected() -> None:
    """An empty cutoff or threshold list would emit nothing; fail loudly instead."""
    for cutoffs, pairs in (((), ((0.0, 0.05),)), ((25,), ())):
        with pytest.raises(ValueError):
            topn_pair_select_sql_v2(
                binding_db="fake_binding",
                perturbation_db="kemmeren",
                binding_table="b",
                binding_hf_repo=B_REPO,
                binding_hf_config=B_CFG,
                perturbation_table="p",
                pert_hf_repo=P_REPO,
                pert_hf_config=P_CFG,
                rank_col="enrichment",
                rank_asc=False,
                top_n_values=cutoffs,
                threshold_pairs=pairs,
                has_pvalue=True,
            )
