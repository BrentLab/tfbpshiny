"""
The Figures queries must restrict the *binding* side to each dataset's filtered samples,
not only the perturbation side.

Before, a regulator's heat-shock or non-standard-condition samples were pooled into the
medians behind figures 1-3 and 6-9.

"""

from __future__ import annotations

import duckdb
import pandas as pd

from tfbpshiny.modules.figures.queries import (
    fetch_agreement,
    fetch_authors_bound,
    fetch_rank_response,
    fetch_topn_percent_responsive,
)
from tfbpshiny.utils.corr_query import per_dataset_sample_clause

NORMAL = {"treatment": {"type": "categorical", "value": ["Normal"]}}


def _conn() -> duckdb.DuckDBPyConnection:
    """
    Two binding datasets (``b1`` filtered, ``b2`` not) and one perturbation dataset.

    Regulator ``R1`` has two binding samples in each: ``s_ok`` (Normal, ratio 0.2) and
    ``s_hs`` (Heat Shock, ratio 0.8).

    """
    conn = duckdb.connect()
    conn.execute(
        "CREATE TABLE dataset_registry (db_name VARCHAR, hf_repo VARCHAR,"
        " hf_config VARCHAR, data_type VARCHAR, promoter_set_id VARCHAR,"
        " binding_method_id VARCHAR, base_label VARCHAR, primary_db_name VARCHAR)"
    )
    conn.execute(
        "INSERT INTO dataset_registry VALUES"
        " ('b1', 'R', 'c1', 'binding', '500bp', 'promoter_enrichment', 'One', NULL),"
        " ('b2', 'R', 'c2', 'binding', '500bp', 'promoter_enrichment', 'Two', NULL),"
        " ('p1', 'R', 'cp', 'perturbation', NULL, NULL, 'Pert', NULL)"
    )
    conn.execute(
        "CREATE TABLE promoter_sets (promoter_set_id VARCHAR, display_name VARCHAR)"
    )
    for db in ("b1", "b2"):
        conn.execute(
            f'CREATE TABLE "{db}_meta" (sample_id VARCHAR, treatment VARCHAR,'
            " regulator_locus_tag VARCHAR)"
        )
        conn.execute(
            f"INSERT INTO \"{db}_meta\" VALUES ('s_ok', 'Normal', 'R1'),"
            " ('s_hs', 'Heat Shock', 'R1')"
        )
    conn.execute(
        "CREATE TABLE topn_results (binding_source_sample VARCHAR,"
        " perturbation_source_sample VARCHAR, regulator_locus_tag VARCHAR,"
        " top_n INTEGER, effect_threshold DOUBLE, pvalue_threshold DOUBLE,"
        " n INTEGER, responsive_ratio DOUBLE)"
    )
    for cfg in ("c1", "c2"):
        for sample, ratio in (("s_ok", 0.2), ("s_hs", 0.8)):
            for top_n in (0, 25):
                conn.execute(
                    "INSERT INTO topn_results VALUES (?, 'R;cp;ps', 'R1', ?, 0.0, 0.05,"
                    " 25, ?)",
                    [f"R;{cfg};{sample}", top_n, ratio],
                )
    return conn


def _pct(df: pd.DataFrame, db: str) -> float:
    return float(df[df["binding_db"] == db].percent_responsive.iloc[0])


def test_binding_filter_is_applied_in_the_top_n_response_query() -> None:
    conn = _conn()
    args = (conn, ["b1", "b2"], "p1", ["R1"], 25)
    unfiltered = fetch_topn_percent_responsive(*args, filters={})
    filtered = fetch_topn_percent_responsive(*args, filters={"b1": NORMAL})
    # b1: only the Normal sample (0.2) once filtered; the median of both is 0.5.
    assert _pct(unfiltered, "b1") == 50.0
    assert _pct(filtered, "b1") == 20.0
    # b2 has no filter, so it keeps both samples and is untouched.
    assert _pct(filtered, "b2") == 50.0


def test_binding_filter_is_applied_in_the_rank_response_and_authors_bound_queries() -> (
    None
):
    conn = _conn()
    rr = fetch_rank_response(conn, ["b1"], "p1", ["R1"], {"b1": NORMAL})
    assert float(rr.percent_responsive.iloc[0]) == 20.0
    ab = fetch_authors_bound(conn, ["b1"], "p1", {"b1": NORMAL})
    assert float(ab.percent_responsive.iloc[0]) == 20.0


def test_a_filtered_dataset_with_no_passing_samples_contributes_no_rows() -> None:
    conn = _conn()
    none_pass = {"treatment": {"type": "categorical", "value": ["no such value"]}}
    out = fetch_topn_percent_responsive(
        conn, ["b1", "b2"], "p1", ["R1"], 25, {"b1": none_pass}
    )
    assert list(out["binding_db"]) == ["b2"]


def test_per_dataset_clause_is_empty_when_nothing_is_filtered() -> None:
    clause, params = per_dataset_sample_clause(_conn(), ["b1", "b2"], {}, "x", "y")
    assert clause == "" and params == []


def test_agreement_filters_both_sides_of_a_pair() -> None:
    conn = _conn()
    conn.execute(
        "CREATE TABLE topn_agreement (source_sample_a VARCHAR, source_sample_b"
        " VARCHAR, comparison_type VARCHAR, regulator_locus_tag VARCHAR, top_n"
        " INTEGER, n_a INTEGER, n_b INTEGER, n_intersect INTEGER)"
    )
    # b1 x b2 for R1 at N=10: every pairing of the Normal / Heat Shock samples.
    for a, b, overlap in (
        ("s_ok", "s_ok", 8),
        ("s_ok", "s_hs", 2),
        ("s_hs", "s_ok", 2),
        ("s_hs", "s_hs", 2),
    ):
        conn.execute(
            "INSERT INTO topn_agreement VALUES (?, ?, 'binding', 'R1', 10, 10, 10, ?)",
            [f"R;c1;{a}", f"R;c2;{b}", overlap],
        )
    both = {"b1": NORMAL, "b2": NORMAL}
    unfiltered = fetch_agreement(conn, "binding", ["b1", "b2"], {})
    filtered = fetch_agreement(conn, "binding", ["b1", "b2"], both)
    one_side = fetch_agreement(conn, "binding", ["b1", "b2"], {"b1": NORMAL})
    assert len(unfiltered) == len(filtered) == 1
    # Only the (Normal, Normal) pairing, overlap 8, survives both filters; either side
    # alone still leaves a heat-shock partner whose overlap of 2 drags the median down.
    from math import log2

    def enrichment(overlap: float) -> float:
        return log2(overlap * 6000 / (10 * 10))

    assert abs(float(filtered.log2_enrichment.iloc[0]) - enrichment(8)) < 1e-9
    assert float(one_side.log2_enrichment.iloc[0]) < enrichment(8)
    assert float(unfiltered.log2_enrichment.iloc[0]) < enrichment(8)
