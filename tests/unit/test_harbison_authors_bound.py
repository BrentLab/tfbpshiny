"""
Unit tests for Harbison's authors'-threshold "bound" set (figure 3).

Checked by executing the generated SQL against a small synthetic DuckDB connection
standing in for the raw Harbison and perturbation views, as for Calling Cards.

"""

from __future__ import annotations

import duckdb
import pandas as pd
import pytest

from tfbpshiny.datasets import PERTURBATION_DATASET_COLUMNS
from tfbpshiny.materialize.comparison.authors_bound import (
    AUTHORS_BOUND_CONFIGS,
    HARBISON_PVALUE_THRESHOLD,
    authors_bound_select_sql,
)
from tfbpshiny.materialize.comparison.topn import TOP_N_ALL


@pytest.fixture(autouse=True)
def _fake_pert_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Give the synthetic ``fake_pert`` view degron's (effect, pvalue) column mapping.

    Scoped to the test so the shared columns table is restored afterwards.

    """
    monkeypatch.setitem(
        PERTURBATION_DATASET_COLUMNS, "fake_pert", ("log2FoldChange", "padj")
    )


def _synthetic_conn() -> duckdb.DuckDBPyConnection:
    """
    A Harbison view (YPD sample s1, non-YPD sample s2) and a perturbation view.

    R1/s1 has targets at p = 0.001 (exactly on the threshold, bound), 0.0005 (bound),
    0.01 (not bound) and T4 (bound, but never measured by the perturbation dataset).
    R1/s2 is a non-YPD sample and must be ignored entirely.

    """
    conn = duckdb.connect()
    conn.execute(
        "CREATE TABLE harbison (sample_id VARCHAR, regulator_locus_tag VARCHAR,"
        " target_locus_tag VARCHAR, pvalue DOUBLE)"
    )
    conn.execute(
        "INSERT INTO harbison VALUES"
        " ('s1', 'R1', 'T1', 0.001),"
        " ('s1', 'R1', 'T2', 0.0005),"
        " ('s1', 'R1', 'T3', 0.01),"
        " ('s1', 'R1', 'T4', 0.0001),"
        " ('s2', 'R1', 'T1', 0.0001)"
    )
    conn.execute("CREATE TABLE harbison_meta (sample_id VARCHAR, condition VARCHAR)")
    conn.execute("INSERT INTO harbison_meta VALUES ('s1', 'YPD'), ('s2', 'SM')")
    conn.execute(
        "CREATE TABLE fake_pert (sample_id VARCHAR, regulator_locus_tag VARCHAR,"
        " target_locus_tag VARCHAR, log2FoldChange DOUBLE, padj DOUBLE)"
    )
    conn.execute(
        "INSERT INTO fake_pert VALUES"
        " ('p1', 'R1', 'T1', 2.0, 0.001),"
        " ('p1', 'R1', 'T2', 2.0, 0.001),"
        " ('p1', 'R1', 'T3', 0.0, 0.9)"
    )
    return conn


def _run(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    sql, params = authors_bound_select_sql(
        AUTHORS_BOUND_CONFIGS["harbison"],
        binding_hf_repo="R",
        binding_hf_config="hb",
        perturbation_view="fake_pert",
        pert_hf_repo="R",
        pert_hf_config="pert",
        effect_threshold=1.0,
        pvalue_threshold=0.05,
    )
    return conn.execute(sql, params).df()


def test_threshold_is_inclusive_and_excludes_weak_targets() -> None:
    df = _run(_synthetic_conn())
    assert len(df) == 1
    row = df.iloc[0]
    # T1 (p == 0.001, on the threshold) and T2 are bound; T3 is above it; T4 is not
    # measured by the perturbation dataset.
    assert row["n"] == 2
    assert row["n_responsive"] == 2
    assert row["responsive_ratio"] == 1.0
    assert row["n_intersecting_targets"] == 3


def test_only_ypd_samples_are_used() -> None:
    df = _run(_synthetic_conn())
    assert list(df["binding_source_sample"]) == ["R;hb;s1"]


def test_rows_are_shaped_like_topn_results() -> None:
    row = _run(_synthetic_conn()).iloc[0]
    assert row["top_n"] == TOP_N_ALL
    assert row["perturbation_source_sample"] == "R;pert;p1"
    assert row["regulator_locus_tag"] == "R1"


def test_threshold_is_a_single_named_constant() -> None:
    assert HARBISON_PVALUE_THRESHOLD == 0.001
