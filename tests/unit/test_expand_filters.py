"""Tests for ``expand_filters_to_variants``: every variant is filtered on its primary's
metadata, which is what keeps samples one-to-one with regulators for the alternate
promoter-set and peak-calling datasets."""

from __future__ import annotations

import duckdb
import pandas as pd

from tfbpshiny.utils.corr_query import expand_filters_to_variants

NORMAL = {"treatment": {"type": "categorical", "value": ["Normal"]}}


def _conn(meta: dict[str, pd.DataFrame]) -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect()
    conn.execute(
        "CREATE TABLE dataset_registry (db_name VARCHAR, primary_db_name VARCHAR)"
    )
    conn.execute(
        "INSERT INTO dataset_registry VALUES ('prim', NULL),"
        " ('var_a', 'prim'), ('var_b', 'prim'), ('other', NULL)"
    )
    for name, df in meta.items():
        conn.register("_m", df)
        conn.execute(f'CREATE TABLE "{name}_meta" AS SELECT * FROM _m')
        conn.unregister("_m")
    return conn


def _frame(*, with_treatment: bool = True) -> pd.DataFrame:
    df = pd.DataFrame({"sample_id": [1, 2], "regulator_locus_tag": ["R1", "R1"]})
    if with_treatment:
        df["treatment"] = ["Normal", "Heat Shock"]
    return df


def test_variants_inherit_their_primarys_filter() -> None:
    conn = _conn({"prim": _frame(), "var_a": _frame(), "var_b": _frame()})
    out = expand_filters_to_variants(conn, {"prim": NORMAL})
    assert out["var_a"] == NORMAL
    assert out["var_b"] == NORMAL
    assert out["prim"] == NORMAL


def test_a_variant_without_the_filter_column_is_left_unfiltered() -> None:
    # e.g. the authors' ChEC-seq peak calls carry no condition column.
    conn = _conn(
        {
            "prim": _frame(),
            "var_a": _frame(with_treatment=False),
            "var_b": _frame(),
        }
    )
    out = expand_filters_to_variants(conn, {"prim": NORMAL})
    assert "var_a" not in out
    assert out["var_b"] == NORMAL


def test_the_primarys_filter_replaces_a_stale_variant_entry() -> None:
    """An edit to the primary on the selection tab must reach its variants."""
    conn = _conn({"prim": _frame(), "var_a": _frame(), "var_b": _frame()})
    stale = {"treatment": {"type": "categorical", "value": ["Heat Shock"]}}
    out = expand_filters_to_variants(conn, {"prim": NORMAL, "var_a": stale})
    assert out["var_a"] == NORMAL


def test_nothing_changes_without_a_primary_filter_and_input_is_not_mutated() -> None:
    conn = _conn({"prim": _frame(), "var_a": _frame(), "var_b": _frame()})
    filters = {"other": NORMAL}
    assert expand_filters_to_variants(conn, filters) == {"other": NORMAL}
    expand_filters_to_variants(conn, {"prim": NORMAL})
    assert filters == {"other": NORMAL}


def test_filtered_variant_is_one_sample_per_regulator() -> None:
    """The point of the filter: a regulator with a heat-shock repeat has one sample."""
    from tfbpshiny.utils.corr_query import get_filtered_sample_ids

    conn = _conn({"prim": _frame(), "var_a": _frame(), "var_b": _frame()})
    spec = expand_filters_to_variants(conn, {"prim": NORMAL})["var_a"]
    assert get_filtered_sample_ids(conn, "var_a", spec) == ["1"]


def test_a_missing_filter_column_is_warned_about_once(caplog) -> None:
    """A variant that cannot take its primary's filter must not be skipped silently."""
    import logging

    from tfbpshiny.utils import corr_query

    corr_query._WARNED_MISSING.clear()
    conn = _conn(
        {"prim": _frame(), "var_a": _frame(with_treatment=False), "var_b": _frame()}
    )
    with caplog.at_level(logging.WARNING, logger="shiny"):
        expand_filters_to_variants(conn, {"prim": NORMAL})
        expand_filters_to_variants(conn, {"prim": NORMAL})
    messages = [r.getMessage() for r in caplog.records if "var_a" in r.getMessage()]
    assert len(messages) == 1
    assert "treatment" in messages[0]
    assert not [r for r in caplog.records if "var_b" in r.getMessage()]


def test_authors_chec_peaks_declares_the_standard_condition_column() -> None:
    """
    ``chec_m2025_peaks`` has no condition column in its data, but every sample is the
    standard condition.

    The collection yaml declares that as a constant so the default ChEC-seq filter
    applies to it like every other variant; dropping the entry would put the dataset
    back to being skipped by the filter.

    """
    from pathlib import Path

    import yaml  # type: ignore[import-untyped]

    config = yaml.safe_load(
        (
            Path(__file__).parents[2] / "tfbpshiny" / "brentlab_yeast_collection.yaml"
        ).read_text()
    )
    entries = [
        ds
        for repo in config["repositories"].values()
        for ds in repo.get("dataset", {}).values()
        if isinstance(ds, dict) and ds.get("db_name") == "chec_m2025_peaks"
    ]
    assert len(entries) == 1
    assert entries[0]["Experimental condition"] == {"expression": "'standard'"}


def test_a_variant_with_no_metadata_table_is_skipped_silently(caplog) -> None:
    """
    A scratch workspace holds metadata only for the datasets it needs.

    A variant whose table is simply absent is not a 'missing column' problem and must
    not be warned about.

    """
    import logging

    from tfbpshiny.utils import corr_query

    corr_query._WARNED_MISSING.clear()
    conn = _conn({"prim": _frame(), "var_a": _frame()})  # var_b has no meta table
    with caplog.at_level(logging.WARNING, logger="shiny"):
        out = expand_filters_to_variants(conn, {"prim": NORMAL})
    assert "var_b" not in out
    assert out["var_a"] == NORMAL
    assert not [r for r in caplog.records if "var_b" in r.getMessage()]
