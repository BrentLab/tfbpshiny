"""
Unit tests for Calling Cards' authors'-threshold "bound" set (figure 3).

Pure SQL-string-builder function, no database access -- checked by executing it
against a small synthetic DuckDB connection standing in for the raw Calling Cards and
perturbation views, matching the pattern already used for `topn.py`'s generators.

"""

from __future__ import annotations

import math

import duckdb
import pandas as pd

from tfbpshiny.materialize.comparison.callingcards_authors_bound import (
    CALLINGCARDS_LOG_POISSON_THRESHOLD,
    callingcards_authors_bound_select_sql,
)
from tfbpshiny.materialize.comparison.topn import TOP_N_ALL


def _synthetic_conn() -> duckdb.DuckDBPyConnection:
    """
    A Calling Cards binding view and a perturbation view sharing three targets.

    Regulator R1 has four scored targets against T1: one strongly bound
    (log_poisson_pval far below threshold), one weakly bound (above threshold), and
    T4 which the perturbation dataset never measures (must not count toward
    ``n_intersecting_targets``). T1 and T2 are responsive; T3 is not.

    """
    conn = duckdb.connect()
    conn.execute(
        "CREATE TABLE callingcards_500bp (sample_id VARCHAR, regulator_locus_tag"
        " VARCHAR, target_locus_tag VARCHAR, log_poisson_pval DOUBLE)"
    )
    conn.execute(
        "INSERT INTO callingcards_500bp VALUES"
        " ('s1', 'R1', 'T1', -20.0),"  # far below threshold -> bound
        " ('s1', 'R1', 'T2', -20.0),"  # far below threshold -> bound
        " ('s1', 'R1', 'T3', -1.0),"  # above threshold -> not bound
        " ('s1', 'R1', 'T4', -20.0)"  # bound, but perturbation never measures T4
    )
    conn.execute(
        "CREATE TABLE fake_pert (sample_id VARCHAR, regulator_locus_tag VARCHAR,"
        " target_locus_tag VARCHAR, log2FoldChange DOUBLE, padj DOUBLE)"
    )
    conn.execute(
        "INSERT INTO fake_pert VALUES"
        " ('p1', 'R1', 'T1', 2.0, 0.001),"  # responsive
        " ('p1', 'R1', 'T2', 2.0, 0.001),"  # responsive
        " ('p1', 'R1', 'T3', 0.0, 0.9)"  # not responsive
    )
    return conn


def _run(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    # A fake perturbation dataset name pointed at the synthetic table, reusing
    # degron's (effect, pvalue) column mapping, so the query's
    # `{perturbation_view}` resolves to our fixture rather than a real dataset.
    import tfbpshiny.materialize.comparison.topn as topn

    topn.PERTURBATION_DATASET_COLUMNS["fake_pert"] = ("log2FoldChange", "padj")
    sql, params = callingcards_authors_bound_select_sql(
        binding_hf_repo="R",
        binding_hf_config="cc",
        perturbation_view="fake_pert",
        pert_hf_repo="R",
        pert_hf_config="pert",
        effect_threshold=1.0,
        pvalue_threshold=0.05,
    )
    return conn.execute(sql, params).df()


def test_threshold_excludes_the_weakly_bound_target() -> None:
    df = _run(_synthetic_conn())
    assert len(df) == 1
    row = df.iloc[0]
    # Bound: T1 and T2 (both below threshold); T3 excluded (above threshold), T4
    # excluded (not measured by the perturbation dataset).
    assert row["n"] == 2
    assert row["n_responsive"] == 2
    assert row["responsive_ratio"] == 1.0
    # Unlike `n` (thresholded), n_intersecting_targets is the full candidate
    # population the perturbation dataset can even speak to -- T1, T2 and T3, but not
    # T4, which the perturbation dataset never measures.
    assert row["n_intersecting_targets"] == 3


def test_rows_are_shaped_like_topn_results() -> None:
    df = _run(_synthetic_conn())
    row = df.iloc[0]
    assert row["top_n"] == TOP_N_ALL
    assert row["binding_source_sample"] == "R;cc;s1"
    assert row["perturbation_source_sample"] == "R;pert;p1"
    assert row["regulator_locus_tag"] == "R1"


def test_threshold_is_a_single_named_constant() -> None:
    """An easily-changed parameter, not threaded through CLI flags -- matches the
    module's stated design."""
    assert CALLINGCARDS_LOG_POISSON_THRESHOLD == math.log(1e-4)


def test_blacklisted_targets_are_excluded() -> None:
    """The five CC_TARGET_BLACKLIST loci must never count as bound, even if scored."""
    from tfbpshiny.materialize.comparison.topn import CC_TARGET_BLACKLIST

    conn = _synthetic_conn()
    blacklisted = CC_TARGET_BLACKLIST[0]
    conn.execute(
        "INSERT INTO callingcards_500bp VALUES (?, 'R1', ?, -20.0)",
        ["s1", blacklisted],
    )
    conn.execute(
        "INSERT INTO fake_pert VALUES (?, 'R1', ?, 2.0, 0.001)",
        ["p1", blacklisted],
    )
    df = _run(conn)
    # Still just T1/T2 -- the blacklisted target must not raise n or n_responsive.
    assert df.iloc[0]["n"] == 2
