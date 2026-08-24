"""Unit tests for the Figures module's pure figure factories."""

from __future__ import annotations

import matplotlib
import pandas as pd
import pytest

matplotlib.use("Agg")

from tfbpshiny.modules.figures.plots import (  # noqa: E402
    dto_significance_bars,
    dto_venn_figure,
    percent_responsive_boxes,
    rank_response_facet,
    rank_response_figure,
)
from tfbpshiny.modules.figures.queries import (  # noqa: E402
    BINDING_ORDER,
    DTO_BINDING_ORDER,
    PR_ORDER,
)

LABELS = {
    "harbison": "2004 ChIP-chip",
    "callingcards": "2026 Calling Cards",
    "rossi": "2021 ChIP-exo",
    "chec_m2025": "2025 ChEC-seq",
    "kemmeren": "2014 TFKO",
    "hackett": "2020 Overexpression",
    "degron": "2025 Degron",
}


@pytest.fixture
def rank_df() -> pd.DataFrame:
    """Two regulators x four binding datasets x five rank points."""
    rows = []
    for reg in ("YAL001C", "YBR002W"):
        for db in BINDING_ORDER:
            for i, n in enumerate((10, 25, 50, 75, 100)):
                rows.append(
                    {
                        "binding_db": db,
                        "regulator_locus_tag": reg,
                        "n": n,
                        # decreasing, so the fixture matches the real shape
                        "percent_responsive": 50.0 - i * 5,
                    }
                )
    return pd.DataFrame(rows)


def test_rank_response_one_trace_per_binding_dataset(rank_df: pd.DataFrame) -> None:
    """One line per binding dataset, and none for datasets with no rows."""
    sub = rank_df[rank_df.regulator_locus_tag == "YAL001C"]
    fig = rank_response_figure(sub, LABELS, list(BINDING_ORDER))
    assert len(fig.data) == len(BINDING_ORDER)
    assert {t.name for t in fig.data} == {LABELS[d] for d in BINDING_ORDER}

    partial = sub[sub.binding_db != "harbison"]
    assert len(rank_response_figure(partial, LABELS, list(BINDING_ORDER)).data) == 3


def test_rank_response_plots_n_not_top_n(rank_df: pd.DataFrame) -> None:
    """The x values come from `n`, which can exceed the nominal cutoff on ties."""
    sub = rank_df[rank_df.regulator_locus_tag == "YAL001C"].copy()
    sub.loc[sub.n == 10, "n"] = 14  # a tie pushed 4 extra targets through
    fig = rank_response_figure(sub, LABELS, list(BINDING_ORDER))
    assert 14 in list(fig.data[0].x)


def test_rank_response_facet_legend_appears_once(rank_df: pd.DataFrame) -> None:
    """Only the first panel contributes to the legend."""
    regs = ["YAL001C", "YBR002W"]
    fig = rank_response_facet(
        rank_df, LABELS, list(BINDING_ORDER), regs, {r: r for r in regs}
    )
    assert len(fig.data) == len(regs) * len(BINDING_ORDER)
    assert sum(1 for t in fig.data if t.showlegend) == len(BINDING_ORDER)


def test_rank_response_facet_empty_regulators() -> None:
    """No regulators yields an empty figure rather than raising."""
    fig = rank_response_facet(pd.DataFrame(), LABELS, list(BINDING_ORDER), [], {})
    assert len(fig.data) == 0


def test_percent_responsive_boxes_outliers_only() -> None:
    """Points are drawn for outliers only, per the figure spec."""
    df = pd.DataFrame(
        {
            "binding_db": ["rossi"] * 5 + ["harbison"] * 5,
            "regulator_locus_tag": [f"R{i}" for i in range(10)],
            "percent_responsive": [10, 12, 14, 16, 90, 5, 6, 7, 8, 9],
        }
    )
    fig = percent_responsive_boxes(df, LABELS, ["rossi", "harbison"])
    assert len(fig.data) == 2
    assert all(t.boxpoints == "outliers" for t in fig.data)


def test_dto_bars_split_count_and_fraction_into_two_rows() -> None:
    """
    Counts and percentages occupy separate rows, each with its own single y axis.

    They shared a twin-axis panel before; a count and a percentage on one panel invite
    reading one against the other's scale.

    """
    rows = [
        {
            "binding_db": b,
            "perturbation_db": p,
            "n_significant": 10,
            "n_covered": 40,
            "n_shared": 50,
            "fraction_significant": 0.2,
        }
        for b in DTO_BINDING_ORDER
        for p in PR_ORDER
    ]
    fig = dto_significance_bars(
        pd.DataFrame(rows), LABELS, list(DTO_BINDING_ORDER), list(PR_ORDER)
    )
    # two bars per perturbation column: one in the count row, one in the fraction row
    assert sum(1 for t in fig.data if t.type == "bar") == 2 * len(PR_ORDER)
    assert not any(t.type == "scatter" for t in fig.data)
    # 2 rows x 3 columns of independent panels
    assert len({t.yaxis for t in fig.data}) == 2 * len(PR_ORDER)
    # no twin axis remains
    assert fig.layout.yaxis2.overlaying is None


def test_dto_bars_skip_missing_pair() -> None:
    """A pair with no row simply produces no bar rather than raising."""
    rows = [
        {
            "binding_db": "rossi",
            "perturbation_db": "kemmeren",
            "n_significant": 5,
            "n_covered": 20,
            "n_shared": 25,
            "fraction_significant": 0.2,
        }
    ]
    fig = dto_significance_bars(
        pd.DataFrame(rows), LABELS, list(DTO_BINDING_ORDER), list(PR_ORDER)
    )
    assert sum(1 for t in fig.data if t.type == "bar") == 2


def test_venn_falls_back_to_equal_circles_when_layout_invalid() -> None:
    """
    Sizes with no valid proportional layout fall back to equal circles.

    matplotlib_venn would otherwise warn and draw areas that do not match the counts,
    which is worse than not implying proportion at all.

    """
    # These are the real DTO/Hackett sizes, which have no valid proportional layout.
    sets = {
        "callingcards": {f"g{i}" for i in range(61)},
        "rossi": {f"g{i}" for i in range(20, 67)},
        "chec_m2025": {f"g{i}" for i in range(5, 63)},
    }
    fig = dto_venn_figure(sets, LABELS, list(DTO_BINDING_ORDER), title="X")
    assert "not to scale" in fig.axes[0].get_title()


def test_venn_keeps_proportional_layout_when_valid() -> None:
    """A well-behaved size combination keeps the area-proportional layout."""
    sets = {
        "callingcards": {f"g{i}" for i in range(30)},
        "rossi": {f"g{i}" for i in range(25, 55)},
        "chec_m2025": {f"g{i}" for i in range(50, 80)},
    }
    fig = dto_venn_figure(sets, LABELS, list(DTO_BINDING_ORDER), title="X")
    assert fig.axes[0].get_title() == "X"


# --- scoring definition pinning -------------------------------------------------


def test_scoring_clause_resolves_preset_per_dataset() -> None:
    """
    Each dataset contributes its own threshold pair, not a global one.

    Kemmeren and Degron have different Stringent cutoffs, so a single global pair would
    silently misread one of them.

    """
    from tfbpshiny.modules.figures.queries import scoring_clause

    _, kem = scoring_clause("kemmeren", "Stringent")
    _, deg = scoring_clause("degron", "Stringent")
    assert kem == [0.77, 0.05]
    assert deg == [0.38, 0.1]


def test_stringent_matches_the_presets_table() -> None:
    """
    Stringent is each dataset's published criteria, so it must track the preset table.

    The figures pin thresholds by value, so a preset edited in `vdb_init.py` without a
    rebuild would read rows that do not exist and render empty.

    """
    from tfbpshiny.modules.figures.queries import scoring_clause
    from tfbpshiny.utils.vdb_init import DEFAULT_RESPONSIVENESS_PRESETS

    for name in ("Relaxed", "Stringent"):
        preset = DEFAULT_RESPONSIVENESS_PRESETS[name]
        for pr_db in ("kemmeren", "degron", "hackett", "hu_reimand"):
            _, params = scoring_clause(pr_db, name)
            assert params == list(preset.get(pr_db, preset["*"]))


def test_scoring_clause_always_pins_both_thresholds() -> None:
    """
    Every call pins the (effect, pvalue) pair.

    Both presets are materialized, so `topn_results` holds more than one row per
    (binding sample, perturbation sample, regulator, top_n); a query that does not
    pin the pair medians across two definitions of responsive and silently reports a
    different number.

    """
    from tfbpshiny.modules.figures.queries import scoring_clause

    for preset in ("Relaxed", "Stringent"):
        clause, params = scoring_clause("degron", preset)
        assert "effect_threshold = ?" in clause
        assert "pvalue_threshold = ?" in clause
        assert len(params) == 2


def test_authors_bound_grid_splits_metrics_into_two_rows() -> None:
    """
    Response rate and bound-set size get a row each rather than sharing twin axes.

    With two boxes in one panel it is never obvious which axis a box belongs to, and the
    two quantities have unrelated units.

    """
    from tfbpshiny.modules.figures.plots import authors_bound_grid

    frames = {
        pr: pd.DataFrame(
            {
                "binding_db": ["rossi_peaks", "chec_m2025_peaks"] * 3,
                "regulator_locus_tag": [f"R{i}" for i in range(6)],
                "percent_responsive": [10.0, 20.0, 30.0, 40.0, 15.0, 25.0],
                "n_bound": [100.0, 200.0, 300.0, 400.0, 150.0, 250.0],
            }
        )
        for pr in ("kemmeren", "degron")
    }
    labels = {
        "rossi_peaks": "2021 ChIP-exo",
        "chec_m2025_peaks": "2025 ChEC-seq",
        "kemmeren": "2014 TFKO",
        "degron": "2025 Degron",
    }
    fig = authors_bound_grid(
        frames,
        labels,
        ["rossi_peaks", "chec_m2025_peaks"],
        ["kemmeren", "degron"],
    )
    # 2 datasets x 2 metrics x 2 perturbation columns
    assert len(fig.data) == 8
    assert len({t.yaxis for t in fig.data}) == 4
    assert fig.layout.annotations[0].text.startswith("A.")
    assert fig.layout.annotations[2].text.startswith("B.")
    # each dataset contributes exactly one legend entry
    assert sum(1 for t in fig.data if t.showlegend) == 2


def test_authors_bound_grid_skips_empty_perturbations() -> None:
    """A perturbation dataset with no rows drops its column instead of raising."""
    from tfbpshiny.modules.figures.plots import authors_bound_grid

    fig = authors_bound_grid({}, {}, ["rossi_peaks"], ["kemmeren"])
    assert len(fig.data) == 0


def test_agreement_pair_is_container_sized_for_a_5050_split() -> None:
    """
    Neither figure 6 panel fixes its width, so the container can split them evenly.

    A fixed `layout.width` would override the flex basis and break the 50/50 split.

    """
    from tfbpshiny.modules.figures.plots import (
        agreement_box_figure,
        agreement_curve_figure,
    )

    curve = agreement_curve_figure(
        pd.DataFrame(
            {
                "pair": ["A vs B"] * 3,
                "top_n": [10, 25, 50],
                "log2_enrichment": [3.0, 2.0, 1.0],
                "regulator_locus_tag": ["R"] * 3,
            }
        )
    )
    box = agreement_box_figure(
        pd.DataFrame(
            {"pair": ["A vs B"] * 4, "weighted_enrichment": [1.0, 2.0, 3.0, 4.0]}
        )
    )
    assert curve.layout.width is None
    assert box.layout.width is None
    assert curve.layout.autosize and box.layout.autosize
    # Equal heights, so the two halves line up.
    assert curve.layout.height == box.layout.height


def test_legends_sit_inside_the_plotting_area() -> None:
    """
    Figures 1 and 6 place the legend inside, in the top-right corner.

    Both plot quantities that fall from left to right, so that corner is empty; an
    outside legend would take width the curves need.

    """
    from tfbpshiny.modules.figures.plots import (
        agreement_curve_figure,
        rank_response_figure,
    )

    rank = rank_response_figure(
        pd.DataFrame(
            {
                "binding_db": ["rossi"] * 3,
                "regulator_locus_tag": ["R"] * 3,
                "n": [10, 25, 50],
                "percent_responsive": [30.0, 20.0, 10.0],
            }
        ),
        LABELS,
        ["rossi"],
    )
    curve = agreement_curve_figure(
        pd.DataFrame(
            {
                "pair": ["A vs B"] * 3,
                "top_n": [10, 25, 50],
                "log2_enrichment": [3.0, 2.0, 1.0],
                "regulator_locus_tag": ["R"] * 3,
            }
        )
    )
    for fig in (rank, curve):
        legend = fig.layout.legend
        assert 0.0 <= legend.x <= 1.0
        assert 0.0 <= legend.y <= 1.0
        assert legend.xanchor == "right" and legend.yanchor == "top"
        # Translucent, so a line passing under it stays visible.
        assert legend.bgcolor.startswith("rgba")


# --- fixed axis ranges ----------------------------------------------------------


def test_percentage_axes_are_pinned_to_0_100(rank_df: pd.DataFrame) -> None:
    """
    Every percentage axis is fixed, not fitted to the data.

    Fitting would make two panels with different spreads look alike, which is the
    opposite of what a cross-dataset comparison needs.

    """
    from tfbpshiny.modules.figures.plots import (
        FIG1_RANK_RESPONSE_Y,
        FIG2_TOPN_BOX_Y,
    )

    sub = rank_df[rank_df.regulator_locus_tag == "YAL001C"]
    rank = rank_response_figure(sub, LABELS, list(BINDING_ORDER))
    assert tuple(rank.layout.yaxis.range) == FIG1_RANK_RESPONSE_Y

    box = percent_responsive_boxes(
        pd.DataFrame(
            {
                "binding_db": ["rossi"] * 3,
                "regulator_locus_tag": list("abc"),
                "percent_responsive": [1.0, 2.0, 3.0],
            }
        ),
        LABELS,
        ["rossi"],
    )
    # A narrow spread must not rescale the axis.
    assert tuple(box.layout.yaxis.range) == FIG2_TOPN_BOX_Y


def test_out_of_range_data_warns_but_axis_holds(caplog) -> None:
    """
    Data outside a fixed range logs a WARNING naming the constant, and is still clipped.

    The axis not moving is the point; the warning is what stops the clipping being
    silent.

    """
    from tfbpshiny.modules.figures.plots import FIG2_TOPN_BOX_Y

    df = pd.DataFrame(
        {
            "binding_db": ["rossi"] * 3,
            "regulator_locus_tag": list("abc"),
            "percent_responsive": [10.0, 50.0, 140.0],  # 140 exceeds the axis
        }
    )
    with caplog.at_level("WARNING", logger="shiny"):
        fig = percent_responsive_boxes(df, LABELS, ["rossi"])
    assert "FIG2_TOPN_BOX_Y" in caplog.text
    assert "clipped" in caplog.text
    assert tuple(fig.layout.yaxis.range) == FIG2_TOPN_BOX_Y


def test_in_range_data_does_not_warn(caplog) -> None:
    """No warning when everything fits."""
    df = pd.DataFrame(
        {
            "binding_db": ["rossi"] * 3,
            "regulator_locus_tag": list("abc"),
            "percent_responsive": [10.0, 50.0, 90.0],
        }
    )
    with caplog.at_level("WARNING", logger="shiny"):
        percent_responsive_boxes(df, LABELS, ["rossi"])
    assert "clipped" not in caplog.text


def test_count_axes_size_from_data_plus_headroom() -> None:
    """
    Figure 4A is a count, so it grows with the data rather than being pinned.

    Pinning a count to 100 would clip as soon as a dataset exceeded 100 significant TFs,
    which the real data already does.

    """
    from tfbpshiny.modules.figures.plots import FIG4A_COUNT_HEADROOM

    rows = [
        {
            "binding_db": b,
            "perturbation_db": p,
            "n_significant": 137,
            "n_covered": 200,
            "n_shared": 250,
            "fraction_significant": 0.5,
        }
        for b in DTO_BINDING_ORDER
        for p in PR_ORDER
    ]
    fig = dto_significance_bars(
        pd.DataFrame(rows), LABELS, list(DTO_BINDING_ORDER), list(PR_ORDER)
    )
    assert tuple(fig.layout.yaxis.range) == (0.0, 137.0 + FIG4A_COUNT_HEADROOM)
    # ...while the percentage row below it stays pinned.
    assert tuple(fig.layout.yaxis4.range) == (0.0, 100.0)


def test_agreement_axes_are_pinned() -> None:
    """Both figure 6 panels share one fixed enrichment range, so they are comparable."""
    from tfbpshiny.modules.figures.plots import (
        FIG6_ENRICHMENT_Y,
        agreement_box_figure,
        agreement_curve_figure,
    )

    curve = agreement_curve_figure(
        pd.DataFrame(
            {
                "pair": ["A vs B"] * 3,
                "top_n": [10, 25, 50],
                "log2_enrichment": [3.0, 2.0, 1.0],
                "regulator_locus_tag": ["R"] * 3,
            }
        )
    )
    box = agreement_box_figure(
        pd.DataFrame({"pair": ["A vs B"] * 3, "weighted_enrichment": [1.0, 2.0, 3.0]})
    )
    assert tuple(curve.layout.yaxis.range) == FIG6_ENRICHMENT_Y
    assert tuple(box.layout.yaxis.range) == FIG6_ENRICHMENT_Y


def test_rank_response_x_axis_is_pinned(caplog) -> None:
    """
    Figure 1's x axis is fixed too, and warns naming the x constant.

    `n` can exceed the largest materialized cutoff when a tie spans it, so this axis
    really does clip real data.

    """
    from tfbpshiny.modules.figures.plots import FIG1_RANK_X

    df = pd.DataFrame(
        {
            "binding_db": ["rossi"] * 2,
            "regulator_locus_tag": ["R"] * 2,
            "n": [10, 150],
            "percent_responsive": [50.0, 20.0],
        }
    )
    with caplog.at_level("WARNING", logger="shiny"):
        fig = rank_response_figure(df, LABELS, ["rossi"])
    assert tuple(fig.layout.xaxis.range) == FIG1_RANK_X
    assert "FIG1_RANK_X" in caplog.text
    # The message must name the axis it is about, not always say "y".
    assert "fixed x axis" in caplog.text


def test_venn_offers_a_named_svg_download() -> None:
    """
    The Venn gets an explicit download link, since it has no plotly modebar.

    Right-clicking a data-URI image gives inconsistent results across browsers and no
    sensible filename, so the anchor carries the name and the `.svg` extension.

    """
    import base64
    import re

    from tfbpshiny.utils.figure import matplotlib_svg_html

    sets = {
        "callingcards": {f"g{i}" for i in range(30)},
        "rossi": {f"g{i}" for i in range(25, 55)},
        "chec_m2025": {f"g{i}" for i in range(50, 80)},
    }
    fig = dto_venn_figure(sets, LABELS, list(DTO_BINDING_ORDER), title="X")
    html = str(matplotlib_svg_html(fig, alt="venn", filename="fig5_test").tagify())

    assert 'download="fig5_test.svg"' in html
    assert "Download SVG" in html
    # The payload must be real vector SVG, not a raster wrapped in an svg tag.
    payload = base64.b64decode(
        re.search(r'href="data:image/svg\+xml;base64,([^"]+)"', html).group(1)
    )
    assert b"<svg" in payload[:500]
    assert b"<path" in payload
    assert b"image/png" not in payload


def test_venn_without_filename_has_no_download_link() -> None:
    """Omitting the filename draws the image alone."""
    from tfbpshiny.utils.figure import matplotlib_svg_html

    sets = {"a": {"g1"}, "b": {"g2"}, "c": {"g3"}}
    fig = dto_venn_figure(sets, {}, ["a", "b", "c"])
    html = str(matplotlib_svg_html(fig).tagify())
    assert "Download SVG" not in html
    assert "<img" in html


# --- stale-schema guard ----------------------------------------------------------


def _fake_topn_db(with_criteria: bool):
    """Build an in-memory `topn_results` with or without the retired column."""
    import duckdb

    conn = duckdb.connect()
    extra = ", criteria VARCHAR" if with_criteria else ""
    conn.execute(f"CREATE TABLE topn_results (top_n INTEGER{extra})")
    return conn


def test_stale_schema_is_reported() -> None:
    """
    A database predating the criteria removal must announce itself.

    Nothing filters `criteria` any more, so its rows are silently averaged in. There
    is no traceback and no empty table -- only a number that reads low.

    """
    import logging

    from tfbpshiny.utils.schema_check import warn_if_stale_topn_schema

    logger = logging.getLogger("test_stale_schema")
    records: list[str] = []
    handler = logging.Handler()
    handler.emit = lambda r: records.append(r.getMessage())  # type: ignore
    logger.addHandler(handler)
    try:
        assert warn_if_stale_topn_schema(_fake_topn_db(True), logger) is True
        assert any("criteria" in m for m in records)
        records.clear()
        assert warn_if_stale_topn_schema(_fake_topn_db(False), logger) is False
        assert records == []
    finally:
        logger.removeHandler(handler)


def test_stale_check_survives_a_missing_table() -> None:
    """A database with no `topn_results` is a different failure, reported elsewhere."""
    import logging

    import duckdb

    from tfbpshiny.utils.schema_check import warn_if_stale_topn_schema

    assert warn_if_stale_topn_schema(duckdb.connect(), logging.getLogger("t")) is False


# --- figure 6 dataset selection --------------------------------------------------


def _agreement_db():
    """In-memory registry + agreement rows covering enrichment and peak variants."""
    import duckdb

    conn = duckdb.connect()
    conn.execute(
        "CREATE TABLE promoter_sets (promoter_set_id VARCHAR, display_name VARCHAR)"
    )
    conn.execute(
        "INSERT INTO promoter_sets VALUES ('kang','Kang'),('500bp','500 bp'),"
        "('peaks','Peaks')"
    )
    conn.execute(
        "CREATE TABLE dataset_registry (db_name VARCHAR, hf_repo VARCHAR,"
        " hf_config VARCHAR, data_type VARCHAR, base_label VARCHAR,"
        " primary_db_name VARCHAR, promoter_set_id VARCHAR,"
        " binding_method_id VARCHAR)"
    )
    conn.execute(
        """INSERT INTO dataset_registry VALUES
        ('rossi','R','kang','binding','ChIP-exo',NULL,'kang','promoter_enrichment'),
        ('rossi_500bp','R','b5','binding','ChIP-exo','rossi','500bp',
         'promoter_enrichment'),
        ('rossi_peaks_500bp','R','p5','binding','ChIP-exo','rossi','500bp',
         'peak_calling'),
        ('rossi_peaks','R','ap','binding','ChIP-exo','rossi','peaks','peak_calling')
        """
    )
    conn.execute(
        "CREATE TABLE topn_agreement (source_sample_a VARCHAR,"
        " source_sample_b VARCHAR, comparison_type VARCHAR,"
        " regulator_locus_tag VARCHAR, top_n INTEGER, n_a INTEGER, n_b INTEGER,"
        " n_intersect INTEGER)"
    )
    return conn


def test_authors_peaks_are_not_selectable() -> None:
    """
    The authors' own peak calls are excluded from figure 6.

    Their regions are not a fixed upstream window, so a pair involving one differs in
    both the caller and the region and cannot be attributed to either.

    """
    from tfbpshiny.modules.figures.queries import agreement_dataset_choices

    choices = agreement_dataset_choices(_agreement_db(), "binding")
    assert "rossi_peaks" not in choices
    assert "rossi_peaks_500bp" in choices


def test_variant_labels_are_distinguishable() -> None:
    """
    Every selectable dataset gets a distinct label.

    `base_label` alone is shared by all variants of one assay, so a promoter-set
    comparison would legend as "ChIP-exo vs ChIP-exo".

    """
    from tfbpshiny.modules.figures.queries import agreement_dataset_choices

    labels = list(agreement_dataset_choices(_agreement_db(), "binding").values())
    assert len(labels) == len(set(labels)), labels
    assert "ChIP-exo 500 bp" in labels
    assert "ChIP-exo 500 bp peaks" in labels


def test_expectation_uses_observed_set_sizes() -> None:
    """
    Enrichment divides by n_a * n_b, not top_n^2.

    A peak set is whatever the caller returned, often far below top_n. Dividing a
    30-target set by 500^2 understates its enrichment ~16-fold, worst at high N where
    the curve is read.

    """
    import math

    from tfbpshiny.modules.figures.queries import GENE_UNIVERSE, fetch_agreement

    conn = _agreement_db()
    # 30 peak targets vs 500 enrichment targets, overlapping in 20.
    conn.execute(
        "INSERT INTO topn_agreement VALUES"
        " ('R;b5;1','R;p5;1','binding','REG1',500,500,30,20)"
    )
    df = fetch_agreement(conn, "binding", ["rossi_500bp", "rossi_peaks_500bp"])
    assert len(df) == 1
    got = float(df["log2_enrichment"].iloc[0])
    assert math.isclose(got, math.log2(20 * GENE_UNIVERSE / (500 * 30)), rel_tol=1e-9)
    # The old top_n^2 denominator would have been far lower.
    assert got > math.log2(20 * GENE_UNIVERSE / (500 * 500))


def test_single_dataset_yields_no_pairs() -> None:
    """One dataset has nothing to compare against, so the query is skipped."""
    from tfbpshiny.modules.figures.queries import fetch_agreement

    assert fetch_agreement(_agreement_db(), "binding", ["rossi"]).empty
    assert fetch_agreement(_agreement_db(), "binding", []).empty


def test_default_selection_is_500bp_promoter_enrichment() -> None:
    """
    The headline view compares assays on one promoter definition.

    Using each assay's primary instead would have silently compared them on Kang.

    """
    from tfbpshiny.modules.figures.queries import AGREEMENT_DEFAULT_BINDING

    assert all(d.endswith("_500bp") for d in AGREEMENT_DEFAULT_BINDING)
    assert not any("peaks" in d for d in AGREEMENT_DEFAULT_BINDING)
