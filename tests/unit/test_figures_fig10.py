"""Unit tests for figure 10 (shared top-N targets): target-set queries, the overlap
boxes and the Venn colour map."""

from __future__ import annotations

import duckdb
import matplotlib
import pandas as pd

matplotlib.use("Agg")

from tfbpshiny.modules.figures.plots import (  # noqa: E402
    dto_venn_figure,
)

#: Stand-in for `dataset_labels()`. Every promoter variant shares its assay's
#: base_label, which is what the colour maps are keyed on, so the Kang and 500 bp
#: entries of one assay deliberately map to the same string.
LABELS = {
    "harbison": "2004 ChIP-chip",
    "callingcards_kang": "2026 Calling Cards",
    "callingcards_500bp": "2026 Calling Cards",
    "rossi": "2021 ChIP-exo",
    "rossi_500bp": "2021 ChIP-exo",
    "chec_m2025": "2025 ChEC-seq",
    "chec_m2025_500bp": "2025 ChEC-seq",
    "kemmeren": "2014 TFKO",
    "hackett": "2020 Overexpression",
    "degron": "2025 Degron",
}


def _target_sets_conn() -> duckdb.DuckDBPyConnection:
    """Two binding datasets (a, b) and one more (c), with ranked target lists."""
    conn = duckdb.connect()
    conn.execute(
        "CREATE TABLE dataset_registry (db_name VARCHAR, hf_repo VARCHAR,"
        " hf_config VARCHAR, data_type VARCHAR, promoter_set_id VARCHAR,"
        " binding_method_id VARCHAR, base_label VARCHAR, primary_db_name VARCHAR)"
    )
    conn.execute(
        "INSERT INTO dataset_registry VALUES"
        " ('a', 'R', 'ca', 'binding', '500bp', 'promoter_enrichment', 'Alpha', 'a'),"
        " ('b', 'R', 'cb', 'binding', '500bp', 'promoter_enrichment', 'Beta', 'b'),"
        " ('c', 'R', 'cc', 'binding', '500bp', 'promoter_enrichment', 'Gamma', 'c')"
    )
    conn.execute(
        "CREATE TABLE promoter_sets (promoter_set_id VARCHAR, display_name VARCHAR)"
    )
    conn.execute(
        "CREATE TABLE topn_target_sets (source_sample VARCHAR, comparison_type"
        " VARCHAR, regulator_locus_tag VARCHAR, target_locus_tag VARCHAR, rnk INTEGER,"
        " db_name VARCHAR, sample_id VARCHAR)"
    )

    def put(db: str, cfg: str, reg: str, targets: list[str]) -> None:
        for i, t in enumerate(targets, start=1):
            conn.execute(
                "INSERT INTO topn_target_sets VALUES (?, 'binding', ?, ?, ?, ?, 's1')",
                [f"R;{cfg};s1", reg, t, i, db],
            )

    put("a", "ca", "R1", ["T1", "T2", "T3", "T4"])
    put("b", "cb", "R1", ["T2", "T9", "T3", "T8"])
    put("c", "cc", "R1", ["T7", "T6", "T5", "T4"])
    # R2 has disjoint a/b sets: must count as 0 shared, not drop out.
    put("a", "ca", "R2", ["T1", "T2"])
    put("b", "cb", "R2", ["T8", "T9"])
    return conn


def test_fetch_shared_targets_counts_overlap_at_the_requested_top_n() -> None:
    from tfbpshiny.modules.figures.queries import fetch_shared_targets

    conn = _target_sets_conn()
    got = {
        (r.pair, r.regulator_locus_tag): r.n_shared
        for r in fetch_shared_targets(conn, "binding", ["a", "b", "c"], 4).itertuples()
    }
    # Pairs are oriented in sorted db_name order, as in figure 6.
    assert got[("Alpha vs Beta", "R1")] == 2.0  # T2, T3
    assert got[("Alpha vs Beta", "R2")] == 0.0  # disjoint, still present
    assert got[("Alpha vs Gamma", "R1")] == 1.0  # T4
    # A shallower cutoff only sees ranks <= N: Alpha {T1,T2} vs Beta {T2,T9}.
    top2 = fetch_shared_targets(conn, "binding", ["a", "b"], 2)
    assert top2.set_index("regulator_locus_tag").n_shared["R1"] == 1.0


def test_fetch_shared_targets_pair_labels_match_figure_6() -> None:
    from tfbpshiny.modules.figures.queries import fetch_agreement, fetch_shared_targets

    conn = _target_sets_conn()
    conn.execute(
        "CREATE TABLE topn_agreement (source_sample_a VARCHAR, source_sample_b"
        " VARCHAR, comparison_type VARCHAR, regulator_locus_tag VARCHAR, top_n"
        " INTEGER, n_a INTEGER, n_b INTEGER, n_intersect INTEGER, db_a VARCHAR,"
        " sample_a VARCHAR, db_b VARCHAR, sample_b VARCHAR)"
    )
    conn.execute(
        "INSERT INTO topn_agreement VALUES ('R;ca;s1', 'R;cb;s1', 'binding', 'R1',"
        " 10, 10, 10, 2, 'a', 's1', 'b', 's1')"
    )
    shared = fetch_shared_targets(conn, "binding", ["a", "b"], 4)
    assert set(shared["pair"]) == set(
        fetch_agreement(conn, "binding", ["a", "b"])["pair"]
    )


def test_fetch_shared_targets_needs_two_datasets() -> None:
    from tfbpshiny.modules.figures.queries import fetch_shared_targets

    assert fetch_shared_targets(_target_sets_conn(), "binding", ["a"], 4).empty


def test_fetch_target_sets_returns_each_datasets_top_n() -> None:
    from tfbpshiny.modules.figures.queries import fetch_target_sets

    sets = fetch_target_sets(_target_sets_conn(), ["a", "b", "c"], "R1", 3)
    assert sets == {
        "a": {"T1", "T2", "T3"},
        "b": {"T2", "T9", "T3"},
        "c": {"T7", "T6", "T5"},
    }
    # An unknown regulator gives empty sets, not an error.
    assert not any(fetch_target_sets(_target_sets_conn(), ["a"], "NOPE", 3).values())


def test_shared_targets_box_figure_has_one_trace_per_pair_in_figure_6_colours() -> None:
    from tfbpshiny.modules.figures.plots import _pair_colors, shared_targets_box_figure

    df = pd.DataFrame(
        {
            "pair": ["A vs B"] * 2 + ["A vs C"] * 2,
            "regulator_locus_tag": ["R1", "R2"] * 2,
            "n_shared": [2.0, 4.0, 1.0, 3.0],
        }
    )
    fig = shared_targets_box_figure(df, top_n=25, title="X")
    assert [t.name for t in fig.data] == ["A vs B", "A vs C"]
    colors = _pair_colors(["A vs B", "A vs C"])
    assert [t.line.color for t in fig.data] == [colors["A vs B"], colors["A vs C"]]
    assert fig.layout.yaxis.title.text == "Targets in common, top 25"


def test_venn_accepts_a_colour_map_for_non_binding_datasets() -> None:
    from matplotlib.colors import to_rgb

    labels = {"p1": "2014 TFKO", "p2": "2020 Overexpression", "p3": "2025 Degron"}
    colours = {
        "2014 TFKO": "#3C5488",
        "2020 Overexpression": "#F39B7F",
        "2025 Degron": "#91D1C2",
    }
    sets = {"p1": {"a", "b"}, "p2": {"b", "c"}, "p3": {"c", "d"}}
    fig, proportional = dto_venn_figure(
        sets, labels, ["p1", "p2", "p3"], colors=colours
    )
    drawn = {
        tuple(round(c, 2) for c in p.get_facecolor()[:3]) for p in fig.axes[0].patches
    }
    for label in labels.values():
        assert tuple(round(c, 2) for c in to_rgb(colours[label])) in drawn


def test_sort_regulators_by_symbol_ignores_case_and_falls_back_to_the_tag() -> None:
    from tfbpshiny.modules.figures.queries import sort_regulators_by_symbol

    symbols = {"YJL110C": "GZF3", "YAL001C": "abf1", "YBR049C": "REB1"}
    tags = ["YJL110C", "YZZ999W", "YBR049C", "YAL001C"]
    # abf1 < GZF3 < REB1 case-insensitively; the symbol-less tag sorts by itself.
    assert sort_regulators_by_symbol(tags, symbols) == [
        "YAL001C",
        "YJL110C",
        "YBR049C",
        "YZZ999W",
    ]
