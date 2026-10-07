"""
Determinism of the materialized numbers.

Two builds of the same database from the same commit must agree. Two things broke that:
floating-point summation order in DuckDB's parallel aggregation, and `ROW_NUMBER()`
numbering tied values arbitrarily. These pin both fixes.

"""

from __future__ import annotations

import duckdb
import pytest

from tfbpshiny.datasets import PERTURBATION_CORRELATION_COLUMNS as CORR_PERT_COLUMNS
from tfbpshiny.datasets import PERTURBATION_DATASET_COLUMNS as TOPN_PERT_COLUMNS
from tfbpshiny.materialize.comparison.agreement import (
    AGREEMENT_RANK_OVERRIDES,
    agreement_pair_select_sql,
    agreement_rank_column,
)
from tfbpshiny.materialize.comparison.correlations import (
    correlation_pair_select_sql,
)
from tfbpshiny.materialize.comparison.topn import (
    topn_pair_select_sql_v2,
)
from tfbpshiny.materialize.rounding import (
    DEFAULT_FLOAT_DECIMALS,
    NO_ROUNDING,
    round_expr,
)

# --- rounding ---------------------------------------------------------------------


def test_round_expr_wraps_and_can_be_disabled() -> None:
    """The helper is the single place rounding is applied or skipped."""
    assert round_expr("corr(a, b)") == f"round(corr(a, b), {DEFAULT_FLOAT_DECIMALS})"
    assert round_expr("corr(a, b)", 3) == "round(corr(a, b), 3)"
    assert round_expr("corr(a, b)", NO_ROUNDING) == "corr(a, b)"


def test_round_expr_rejects_a_nonsense_precision() -> None:
    """A negative precision that is not the sentinel is a mistake, not 'no rounding'."""
    with pytest.raises(ValueError):
        round_expr("x", -5)


def test_default_precision_clears_the_observed_noise() -> None:
    """
    1e-9 sits far above the drift actually measured between two builds.

    Two real builds disagreed by at most 1.17e-13 on `correlations.correlation`.
    Rounding must be coarse enough to erase that and fine enough to keep the value
    useful; this pins the margin rather than leaving the constant unexplained.

    """
    observed_noise = 1.17e-13
    resolution = 10.0**-DEFAULT_FLOAT_DECIMALS
    assert resolution > observed_noise * 100, "too fine to absorb the measured drift"
    assert resolution < 1e-6, "too coarse -- would lose real precision"


def test_correlation_sql_rounds_both_methods() -> None:
    """Spearman and Pearson take different code paths; both must round."""
    for method in ("spearman", "pearson"):
        sql, _ = correlation_pair_select_sql(
            view_a="a",
            hf_repo_a="R",
            hf_config_a="c",
            effect_col_a="e",
            pvalue_col_a="p",
            view_b="b",
            hf_repo_b="R",
            hf_config_b="d",
            effect_col_b="e",
            pvalue_col_b="p",
            method=method,
            comparison_type="binding",
        )
        lines = [ln for ln in sql.splitlines() if "AS correlation" in ln]
        assert lines, method
        for ln in lines:
            assert f", {DEFAULT_FLOAT_DECIMALS})" in ln, (method, ln)


def test_correlation_sql_can_store_raw_values() -> None:
    """`--float-decimals -1` must reach the SQL, not be silently ignored."""
    sql, _ = correlation_pair_select_sql(
        view_a="a",
        hf_repo_a="R",
        hf_config_a="c",
        effect_col_a="e",
        pvalue_col_a="p",
        view_b="b",
        hf_repo_b="R",
        hf_config_b="d",
        effect_col_b="e",
        pvalue_col_b="p",
        method="pearson",
        comparison_type="binding",
        round_decimals=NO_ROUNDING,
    )
    assert not any("round(corr" in ln for ln in sql.splitlines())


def test_responsive_ratio_is_rounded() -> None:
    """The other computed float in the database."""
    sql, _ = topn_pair_select_sql_v2(
        binding_table="b",
        binding_hf_repo="R",
        binding_hf_config="c",
        perturbation_table="p",
        pert_hf_repo="R",
        pert_hf_config="d",
        rank_col="enrichment",
        rank_asc=False,
        top_n_values=(25,),
        threshold_pairs=((0.0, 0.05),),
        has_pvalue=True,
    )
    line = [ln for ln in sql.splitlines() if "AS responsive_ratio" in ln][0]
    assert line.strip().startswith("round(")


def test_rounding_actually_collapses_last_bit_drift() -> None:
    """
    Round-tripping through SQL, two values differing at 1e-13 must become one.

    Asserting on the generated string alone would not catch a precision passed in a way
    DuckDB ignores.

    """
    conn = duckdb.connect()
    a, b = 0.1234567890123456, 0.1234567890124456  # differ at ~1e-13
    expr_a = round_expr(repr(a), DEFAULT_FLOAT_DECIMALS)
    expr_b = round_expr(repr(b), DEFAULT_FLOAT_DECIMALS)
    ra, rb = conn.execute(f"SELECT {expr_a}, {expr_b}").fetchone()
    assert a != b
    assert ra == rb


# --- agreement tiebreak -----------------------------------------------------------


def test_agreement_orders_by_a_unique_final_key() -> None:
    """
    `ROW_NUMBER()` over a tied column is arbitrary; the tiebreak makes it total.

    Without `target_locus_tag` the same query run twice disagreed on 24.4% of one
    pair's rows.

    """
    sql, _ = agreement_pair_select_sql(
        view_a="x",
        hf_repo_a="R",
        hf_config_a="c",
        sample_col_a="sample_id",
        rank_col_a="poisson_pval",
        rank_asc_a=True,
        view_b="y",
        hf_repo_b="R",
        hf_config_b="d",
        sample_col_b="sample_id",
        rank_col_b="enrichment",
        rank_asc_b=False,
        comparison_type="binding",
    )
    orders = [ln.strip() for ln in sql.splitlines() if "ORDER BY" in ln]
    assert len(orders) == 2, orders
    for ln in orders:
        assert ln.endswith("target_locus_tag"), ln


def test_tiebreak_makes_row_number_reproducible() -> None:
    """
    End-to-end: an all-tied ranking column must still rank identically every run.

    This is the property the whole change exists for.
    """
    conn = duckdb.connect()
    conn.execute(
        "CREATE TABLE t (sample_id INTEGER, regulator_locus_tag VARCHAR,"
        " target_locus_tag VARCHAR, v DOUBLE)"
    )
    conn.executemany(
        "INSERT INTO t VALUES (1, 'REG1', ?, 0.0)", [(f"T{i:03d}",) for i in range(200)]
    )
    q = """
    SELECT target_locus_tag FROM (
      SELECT target_locus_tag,
             ROW_NUMBER() OVER (PARTITION BY sample_id, regulator_locus_tag
                                ORDER BY v ASC, target_locus_tag) AS rnk
      FROM t
    ) WHERE rnk <= 10 ORDER BY rnk
    """
    first = conn.execute(q).fetchall()
    for _ in range(5):
        assert conn.execute(q).fetchall() == first
    # And it is the deterministic choice, not merely a repeated accident.
    assert [r[0] for r in first] == [f"T{i:03d}" for i in range(10)]


# --- ranking-column overrides -----------------------------------------------------


def test_overrides_do_not_leak_into_responsiveness() -> None:
    """
    Hackett ranks on the cleaned ratio but is still *scored* on the shrunken one.

    Conflating the two would silently redefine what 'responsive' means for hackett and
    change every published topn_results number for it.

    """
    assert CORR_PERT_COLUMNS["hackett"][0] == "log2_cleaned_ratio"
    assert TOPN_PERT_COLUMNS["hackett"][0] == "log2_shrunken_timecourses"


def test_all_four_callingcards_configs_rank_on_the_log_pvalue() -> None:
    """A partial override would make the four Calling Cards sets incomparable."""
    cc = {k: v for k, v in AGREEMENT_RANK_OVERRIDES.items() if k.startswith("calling")}
    assert len(cc) == 4, cc
    for db, (col, asc) in cc.items():
        assert col == "log_poisson_pval", db
        assert asc is True, f"{db}: smaller p must rank better"


def test_datasets_without_an_override_keep_their_defaults() -> None:
    """The override map must not change ranking for anything it does not name."""
    assert agreement_rank_column("rossi", "enrichment", False) == ("enrichment", False)
    assert agreement_rank_column("harbison", "pvalue", True) == ("pvalue", True)
    assert agreement_rank_column("kemmeren", "Madj", False) == ("Madj", False)
