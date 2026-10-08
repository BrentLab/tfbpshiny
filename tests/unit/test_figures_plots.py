"""Unit tests for the Figures module's plot factories (``figures/plots.py``)."""

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


def test_label_stub_covers_every_dataset_the_figures_ask_for() -> None:
    """
    The fixture must track the real constants.

    Renaming a db_name in `BINDING_ORDER` without updating this stub produced a bare
    KeyError deep inside a plot factory; this says what actually went wrong.

    """
    for name in (*BINDING_ORDER, *DTO_BINDING_ORDER, *PR_ORDER):
        assert name in LABELS, f"{name} missing from the test label stub"


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


def test_rank_response_draws_calling_cards_last(rank_df: pd.DataFrame) -> None:
    """
    Calling Cards is drawn on top, so its line stays visible when curves overlap.

    Plotly paints traces in the order they are added -- the last trace added is on
    top -- so this checks draw order, not legend order (which is independent, see
    below).

    """
    sub = rank_df[rank_df.regulator_locus_tag == "YAL001C"]
    fig = rank_response_figure(sub, LABELS, list(BINDING_ORDER))
    assert fig.data[-1].name == "2026 Calling Cards"


def test_rank_response_legend_order_by_top_10_response(rank_df: pd.DataFrame) -> None:
    """
    Legend order is independent of draw order: highest response at the smallest n
    first.

    """
    sub = rank_df[rank_df.regulator_locus_tag == "YAL001C"].copy()
    # Give harbison the highest response rate at n=10, so it must lead the legend even
    # though it is drawn first (not last, like Calling Cards).
    sub.loc[(sub.binding_db == "harbison") & (sub.n == 10), "percent_responsive"] = 99.0
    fig = rank_response_figure(sub, LABELS, list(BINDING_ORDER))
    by_rank = sorted(fig.data, key=lambda t: t.legendrank)
    assert by_rank[0].name == "2004 ChIP-chip"


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


def test_dto_bars_single_row_annotated_with_shared_count() -> None:
    """
    One bar per (binding, perturbation) pair, in a single row.

    The count row was dropped: the fraction's own raw counts (``n_significant`` over
    ``n_shared``, the two-way regulator intersection of that pair) are exactly what a
    reader would have read off the count row, so they are annotated directly on the
    fraction bar instead, as "significant/shared".

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
    # one bar per perturbation column now, not two
    assert sum(1 for t in fig.data if t.type == "bar") == len(PR_ORDER)
    assert not any(t.type == "scatter" for t in fig.data)
    # one panel (one y axis) per perturbation column, not two
    assert len({t.yaxis for t in fig.data}) == len(PR_ORDER)
    # every bar carries "significant/shared" as its text label
    for trace in fig.data:
        assert all(str(t) == "10/50" for t in trace.text)


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
    assert sum(1 for t in fig.data if t.type == "bar") == 1


def test_venn_falls_back_to_equal_circles_when_layout_invalid() -> None:
    """
    Sizes with no valid proportional layout fall back to equal circles.

    matplotlib_venn would otherwise warn and draw areas that do not match the counts,
    which is worse than not implying proportion at all.

    """
    # These are the real DTO/Hackett sizes, which have no valid proportional layout.
    sets = {
        DTO_BINDING_ORDER[0]: {f"g{i}" for i in range(61)},
        DTO_BINDING_ORDER[1]: {f"g{i}" for i in range(20, 67)},
        DTO_BINDING_ORDER[2]: {f"g{i}" for i in range(5, 63)},
    }
    fig, proportional = dto_venn_figure(
        sets, LABELS, list(DTO_BINDING_ORDER), title="X"
    )
    assert proportional is False
    assert fig.axes[0].get_title() == "X"


def test_venn_circles_use_the_binding_dataset_colours() -> None:
    """Fig 5's circles share the colour each dataset has in every other figure."""
    from matplotlib.colors import to_rgb

    from tfbpshiny.utils.figure import BINDING_COLORS

    sets = {
        DTO_BINDING_ORDER[0]: {f"g{i}" for i in range(30)},
        DTO_BINDING_ORDER[1]: {f"g{i}" for i in range(25, 55)},
        DTO_BINDING_ORDER[2]: {f"g{i}" for i in range(50, 80)},
    }
    fig, proportional = dto_venn_figure(
        sets, LABELS, list(DTO_BINDING_ORDER), title="X"
    )
    # Patches are the first three artists in set order (A only, B only, C only
    # regions are drawn in "100", "010", "001" order is not guaranteed), so compare
    # as sets of RGB triples.
    drawn = {
        tuple(round(c, 2) for c in p.get_facecolor()[:3]) for p in fig.axes[0].patches
    }
    for db in DTO_BINDING_ORDER:
        expected = tuple(round(c, 2) for c in to_rgb(BINDING_COLORS[LABELS[db]]))
        assert expected in drawn


def test_venn_keeps_proportional_layout_when_valid() -> None:
    """A well-behaved size combination keeps the area-proportional layout."""
    sets = {
        DTO_BINDING_ORDER[0]: {f"g{i}" for i in range(30)},
        DTO_BINDING_ORDER[1]: {f"g{i}" for i in range(25, 55)},
        DTO_BINDING_ORDER[2]: {f"g{i}" for i in range(50, 80)},
    }
    fig, proportional = dto_venn_figure(
        sets, LABELS, list(DTO_BINDING_ORDER), title="X"
    )
    assert proportional is True
    assert fig.axes[0].get_title() == "X"


def test_venn_cost_based_layout_stays_proportional_where_default_cannot() -> None:
    """The cost-based layout stays proportional on exactly the real-world sizes that
    force the default layout to fall back to equal circles."""
    from tfbpshiny.modules.figures.plots import DTO_VENN_LAYOUT_COST_BASED

    sets = {
        DTO_BINDING_ORDER[0]: {f"g{i}" for i in range(61)},
        DTO_BINDING_ORDER[1]: {f"g{i}" for i in range(20, 67)},
        DTO_BINDING_ORDER[2]: {f"g{i}" for i in range(5, 63)},
    }
    fig, proportional = dto_venn_figure(
        sets,
        LABELS,
        list(DTO_BINDING_ORDER),
        title="X",
        layout=DTO_VENN_LAYOUT_COST_BASED,
    )
    assert proportional is True
    assert fig.axes[0].get_title() == "X"


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


def test_vertical_gridlines_are_off_horizontal_stay_on(rank_df: pd.DataFrame) -> None:
    """
    Every figure drops x-axis (vertical) gridlines but keeps y-axis (horizontal) ones.

    Applied once in ``apply_figure_style``, so any figure factory picks it up for
    free; checked here against figure 1 as a representative case.

    """
    sub = rank_df[rank_df.regulator_locus_tag == "YAL001C"]
    fig = rank_response_figure(sub, LABELS, list(BINDING_ORDER))
    assert fig.layout.xaxis.showgrid is False
    assert fig.layout.yaxis.showgrid is not False


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


def test_dto_bars_axis_stays_pinned_to_0_100() -> None:
    """Figure 4's only remaining row is a percentage, pinned like every other one."""
    from tfbpshiny.modules.figures.plots import FIG4B_FRACTION_Y

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
    assert tuple(fig.layout.yaxis.range) == FIG4B_FRACTION_Y


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


def test_agreement_curve_x_axis_is_linear_from_zero() -> None:
    """The x axis is linear, ticked every 10 units, and starts at 0 -- not the smallest
    plotted cutoff (10) -- so the curve's rise from the origin isn't cropped."""
    from tfbpshiny.modules.figures.plots import (
        FIG6_TOP_N_DTICK,
        FIG6_TOP_N_X,
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
    assert curve.layout.xaxis.type == "linear"
    assert curve.layout.xaxis.dtick == FIG6_TOP_N_DTICK
    assert tuple(curve.layout.xaxis.range) == FIG6_TOP_N_X


def test_agreement_curve_drops_horizontal_gridlines_box_keeps_them() -> None:
    """The line plot drops y gridlines; the box plot -- one series per category -- keeps
    them."""
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
        pd.DataFrame({"pair": ["A vs B"] * 3, "weighted_enrichment": [1.0, 2.0, 3.0]})
    )
    assert curve.layout.yaxis.showgrid is False
    assert box.layout.yaxis.showgrid is not False


def test_agreement_pair_colors_are_distinct_from_single_dataset_colors() -> None:
    """Pairs get their own palette, not `BINDING_COLORS`/`PERTURBATION_COLORS` -- a pair
    is not "the dataset that happens to be tinted red" the way a single-series figure's
    line is, so reusing that palette risks a reader misreading it as one."""
    from tfbpshiny.modules.figures.plots import agreement_curve_figure
    from tfbpshiny.utils.figure import BINDING_COLORS, PERTURBATION_COLORS

    curve = agreement_curve_figure(
        pd.DataFrame(
            {
                "pair": ["A vs B", "C vs D"],
                "top_n": [10, 10],
                "log2_enrichment": [3.0, 1.0],
                "regulator_locus_tag": ["R", "R"],
            }
        )
    )
    single_dataset_colors = set(BINDING_COLORS.values()) | set(
        PERTURBATION_COLORS.values()
    )
    for trace in curve.data:
        assert trace.line.color not in single_dataset_colors


def test_agreement_pair_colors_match_between_curve_and_box() -> None:
    """The same pair gets the same colour in the curve and box panels of one block."""
    from tfbpshiny.modules.figures.plots import (
        agreement_box_figure,
        agreement_curve_figure,
    )

    curve = agreement_curve_figure(
        pd.DataFrame(
            {
                "pair": ["A vs B", "C vs D"],
                "top_n": [10, 10],
                "log2_enrichment": [3.0, 1.0],
                "regulator_locus_tag": ["R", "R"],
            }
        )
    )
    box = agreement_box_figure(
        pd.DataFrame({"pair": ["A vs B", "C vs D"], "weighted_enrichment": [1.0, 2.0]})
    )
    curve_colors = {t.name: t.line.color for t in curve.data}
    box_colors = {t.name: t.line.color for t in box.data}
    assert curve_colors == box_colors


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
        DTO_BINDING_ORDER[0]: {f"g{i}" for i in range(30)},
        DTO_BINDING_ORDER[1]: {f"g{i}" for i in range(25, 55)},
        DTO_BINDING_ORDER[2]: {f"g{i}" for i in range(50, 80)},
    }
    fig, proportional = dto_venn_figure(
        sets, LABELS, list(DTO_BINDING_ORDER), title="X"
    )
    html = str(matplotlib_svg_html(fig, alt="venn", filename="fig5_test").tagify())

    assert 'download="fig5_test.svg"' in html
    assert "Download SVG" in html
    # The payload must be real vector SVG, not a raster wrapped in an svg tag.
    match = re.search(r'href="data:image/svg\+xml;base64,([^"]+)"', html)
    assert match is not None, "no data-URI href in the rendered anchor"
    payload = base64.b64decode(match.group(1))
    assert b"<svg" in payload[:500]
    assert b"<path" in payload
    assert b"image/png" not in payload


def test_venn_without_filename_has_no_download_link() -> None:
    """Omitting the filename draws the image alone."""
    from tfbpshiny.utils.figure import matplotlib_svg_html

    sets = {"a": {"g1"}, "b": {"g2"}, "c": {"g3"}}
    fig, proportional = dto_venn_figure(sets, {}, ["a", "b", "c"])
    html = str(matplotlib_svg_html(fig).tagify())
    assert "Download SVG" not in html
    assert "<img" in html


# --- figure 6 weight-decay illustration ------------------------------------------


def _agreement_curve_df() -> pd.DataFrame:
    """A single-pair, single-regulator curve over the real cutoff grid."""
    cutoffs = list(range(10, 210, 10))
    return pd.DataFrame(
        {
            "pair": ["A vs B"] * len(cutoffs),
            "top_n": cutoffs,
            "log2_enrichment": [3.0 - n / 100 for n in cutoffs],
            "regulator_locus_tag": ["R"] * len(cutoffs),
        }
    )


def test_no_half_life_omits_the_weight_trace() -> None:
    """Existing callers that never pass `half_life` must see no behavior change."""
    from tfbpshiny.modules.figures.plots import agreement_curve_figure

    fig = agreement_curve_figure(_agreement_curve_df())
    assert len(fig.data) == 1
    assert "yaxis2" not in fig.layout


def test_half_life_adds_exactly_one_weight_trace_on_its_own_axis() -> None:
    """
    The weight curve is illustrative, not data: one extra trace, own scale.

    It must not touch `FIG6_ENRICHMENT_Y` or perturb the enrichment traces already on
    the plot -- it answers "how much does this cutoff count", not "how much overlap".

    """
    from tfbpshiny.modules.figures.plots import agreement_curve_figure

    fig = agreement_curve_figure(_agreement_curve_df(), half_life=20)
    assert len(fig.data) == 2
    weight_trace = fig.data[-1]
    assert weight_trace.yaxis == "y2"
    assert fig.layout.yaxis2.overlaying == "y"
    assert fig.layout.yaxis2.side == "right"
    assert tuple(fig.layout.yaxis2.range) == (0, 1)
    # The enrichment trace's own axis is untouched.
    assert fig.data[0].yaxis in (None, "y")


def test_weight_trace_matches_the_box_plot_weighting_exactly() -> None:
    """
    The illustration must be the actual weight, not merely something shaped like it.

    Divergence here would show a reader a decay that does not match what the box plot to
    its right actually computed.

    """
    from tfbpshiny.modules.figures.plots import agreement_curve_figure

    half_life = 30
    df = _agreement_curve_df()
    fig = agreement_curve_figure(df, half_life=half_life)
    weight_trace = fig.data[-1]
    expected = {n: 2.0 ** (-n / half_life) for n in sorted(df["top_n"].unique())}
    for x, y in zip(weight_trace.x, weight_trace.y):
        assert y == pytest.approx(expected[x])


def test_weight_trace_spans_the_full_cutoff_grid_present() -> None:
    """The illustration must cover every cutoff in the data, not just one pair's."""
    from tfbpshiny.modules.figures.plots import agreement_curve_figure

    fig = agreement_curve_figure(_agreement_curve_df(), half_life=10)
    weight_trace = fig.data[-1]
    assert sorted(weight_trace.x) == list(range(10, 210, 10))


def test_half_life_one_at_n_zero_and_decays_thereafter() -> None:
    """Sanity check on the formula: weight is 1 at N=0 and falls monotonically."""
    from tfbpshiny.modules.figures.plots import agreement_curve_figure

    fig = agreement_curve_figure(_agreement_curve_df(), half_life=50)
    weight_trace = fig.data[-1]
    ys = [
        weight_trace.y[i]
        for i in sorted(range(len(weight_trace.x)), key=lambda i: weight_trace.x[i])
    ]
    assert ys[0] < 1.0  # smallest cutoff here is N=10, already decayed a bit
    assert all(a >= b for a, b in zip(ys, ys[1:])), "weight must be monotone decreasing"


def test_empty_dataframe_with_half_life_does_not_crash() -> None:
    """An empty curve (e.g. no data for the featured TF) must not add a phantom
    trace."""
    from tfbpshiny.modules.figures.plots import agreement_curve_figure

    fig = agreement_curve_figure(
        pd.DataFrame(columns=["pair", "top_n", "log2_enrichment"]), half_life=10
    )
    assert len(fig.data) == 0


def _grid_panels() -> dict:
    return {
        ("b1", "p1"): pd.DataFrame(
            {"box_key": ["kang", "kang", "mindel"], "value": [1, 2, 3]}
        ),
        ("b1", "p2"): pd.DataFrame({"box_key": ["kang", "mindel"], "value": [4, 5]}),
        ("b2", "p1"): pd.DataFrame({"box_key": ["mindel"], "value": [6]}),
        # ("b2", "p2") deliberately absent -- must not raise.
    }


def test_box_grid_trace_count_and_shape() -> None:
    from tfbpshiny.modules.figures.plots import binding_perturbation_box_grid

    fig = binding_perturbation_box_grid(
        _grid_panels(),
        ["b1", "b2"],
        ["p1", "p2"],
        ["kang", "mindel"],
        {"b1": "Binding 1", "b2": "Binding 2"},
        {"p1": "P1", "p2": "P2"},
        {"kang": "Kang", "mindel": "Mindel"},
        {"kang": "#377EB8", "mindel": "#4DAF4A"},
        y_title="Test metric",
    )
    # (b1,p1): 2 boxes, (b1,p2): 2 boxes, (b2,p1): 1 box, (b2,p2): 0 boxes.
    assert len(fig.data) == 5


def test_box_grid_legend_appears_once_per_box_key_even_if_first_cell_lacks_one() -> (
    None
):
    """Legend dedup must be per box_key across the whole grid, not "first panel only" --
    (b1,p1) here is missing "mindel", so relying on "first panel" would drop it from the
    legend entirely."""
    from tfbpshiny.modules.figures.plots import binding_perturbation_box_grid

    panels = {
        ("b1", "p1"): pd.DataFrame({"box_key": ["kang"], "value": [1]}),
        ("b1", "p2"): pd.DataFrame({"box_key": ["kang", "mindel"], "value": [2, 3]}),
    }
    fig = binding_perturbation_box_grid(
        panels,
        ["b1"],
        ["p1", "p2"],
        ["kang", "mindel"],
        {"b1": "Binding 1"},
        {"p1": "P1", "p2": "P2"},
        {"kang": "Kang", "mindel": "Mindel"},
        {"kang": "#377EB8", "mindel": "#4DAF4A"},
        y_title="Test metric",
    )
    shown = {t.name for t in fig.data if t.showlegend}
    assert shown == {"Kang", "Mindel"}
    assert sum(1 for t in fig.data if t.showlegend) == 2


def test_box_grid_row_and_column_titles_match_labels() -> None:
    from tfbpshiny.modules.figures.plots import binding_perturbation_box_grid

    fig = binding_perturbation_box_grid(
        _grid_panels(),
        ["b1", "b2"],
        ["p1", "p2"],
        ["kang", "mindel"],
        {"b1": "Binding 1", "b2": "Binding 2"},
        {"p1": "P1", "p2": "P2"},
        {"kang": "Kang", "mindel": "Mindel"},
        {"kang": "#377EB8", "mindel": "#4DAF4A"},
        y_title="Test metric",
    )
    texts = {a.text for a in fig.layout.annotations}
    assert {"Binding 1", "Binding 2", "P1", "P2"} <= texts


def test_box_grid_y_range_applied_when_given() -> None:
    from tfbpshiny.modules.figures.plots import binding_perturbation_box_grid

    fig = binding_perturbation_box_grid(
        _grid_panels(),
        ["b1", "b2"],
        ["p1", "p2"],
        ["kang", "mindel"],
        {"b1": "Binding 1", "b2": "Binding 2"},
        {"p1": "P1", "p2": "P2"},
        {"kang": "Kang", "mindel": "Mindel"},
        {"kang": "#377EB8", "mindel": "#4DAF4A"},
        y_title="Test metric",
        y_range=(0.0, 100.0),
    )
    assert tuple(fig.layout.yaxis.range) == (0.0, 100.0)


# --- binding_perturbation_bar_grid (figures 8/9's DTO bars) ---------------------


def _grid_bar_panels() -> dict:
    return {
        ("b1", "p1"): pd.DataFrame(
            {
                "box_key": ["kang", "mindel"],
                "n_significant": [5, 3],
                "n_shared": [10, 10],
                "fraction_significant": [0.5, 0.3],
            }
        ),
        ("b1", "p2"): pd.DataFrame(
            {
                "box_key": ["kang"],
                "n_significant": [2],
                "n_shared": [8],
                "fraction_significant": [0.25],
            }
        ),
        # ("b2", "p1") / ("b2", "p2") deliberately absent -- must not raise.
    }


def test_bar_grid_trace_count_and_shape() -> None:
    from tfbpshiny.modules.figures.plots import binding_perturbation_bar_grid

    fig = binding_perturbation_bar_grid(
        _grid_bar_panels(),
        ["b1", "b2"],
        ["p1", "p2"],
        ["kang", "mindel"],
        {"b1": "Binding 1", "b2": "Binding 2"},
        {"p1": "P1", "p2": "P2"},
        {"kang": "Kang", "mindel": "Mindel"},
        {"kang": "#377EB8", "mindel": "#4DAF4A"},
    )
    # (b1,p1): 2 bars, (b1,p2): 1 bar, (b2,p1)/(b2,p2): 0 bars.
    assert len(fig.data) == 3
    assert all(t.type == "bar" for t in fig.data)


def test_bar_grid_legend_appears_once_per_box_key_even_if_first_cell_lacks_one() -> (
    None
):
    """Same dedup rule as the box grid: a box_key missing from the first cell it
    appears in must still get exactly one legend entry, from wherever it first
    occurs."""
    from tfbpshiny.modules.figures.plots import binding_perturbation_bar_grid

    panels = {
        ("b1", "p1"): pd.DataFrame(
            {
                "box_key": ["kang"],
                "n_significant": [1],
                "n_shared": [10],
                "fraction_significant": [0.1],
            }
        ),
        ("b1", "p2"): pd.DataFrame(
            {
                "box_key": ["kang", "mindel"],
                "n_significant": [2, 3],
                "n_shared": [10, 10],
                "fraction_significant": [0.2, 0.3],
            }
        ),
    }
    fig = binding_perturbation_bar_grid(
        panels,
        ["b1"],
        ["p1", "p2"],
        ["kang", "mindel"],
        {"b1": "Binding 1"},
        {"p1": "P1", "p2": "P2"},
        {"kang": "Kang", "mindel": "Mindel"},
        {"kang": "#377EB8", "mindel": "#4DAF4A"},
    )
    shown = {t.name for t in fig.data if t.showlegend}
    assert shown == {"Kang", "Mindel"}
    assert sum(1 for t in fig.data if t.showlegend) == 2


def test_bar_grid_row_and_column_titles_match_labels() -> None:
    from tfbpshiny.modules.figures.plots import binding_perturbation_bar_grid

    fig = binding_perturbation_bar_grid(
        _grid_bar_panels(),
        ["b1", "b2"],
        ["p1", "p2"],
        ["kang", "mindel"],
        {"b1": "Binding 1", "b2": "Binding 2"},
        {"p1": "P1", "p2": "P2"},
        {"kang": "Kang", "mindel": "Mindel"},
        {"kang": "#377EB8", "mindel": "#4DAF4A"},
    )
    texts = {a.text for a in fig.layout.annotations}
    assert {"Binding 1", "Binding 2", "P1", "P2"} <= texts


def test_bar_grid_axis_stays_pinned_to_0_100() -> None:
    from tfbpshiny.modules.figures.plots import (
        FIG4B_FRACTION_Y,
        binding_perturbation_bar_grid,
    )

    fig = binding_perturbation_bar_grid(
        _grid_bar_panels(),
        ["b1", "b2"],
        ["p1", "p2"],
        ["kang", "mindel"],
        {"b1": "Binding 1", "b2": "Binding 2"},
        {"p1": "P1", "p2": "P2"},
        {"kang": "Kang", "mindel": "Mindel"},
        {"kang": "#377EB8", "mindel": "#4DAF4A"},
    )
    assert tuple(fig.layout.yaxis.range) == FIG4B_FRACTION_Y


def test_bar_grid_text_labels_are_significant_over_shared_counts() -> None:
    from tfbpshiny.modules.figures.plots import binding_perturbation_bar_grid

    fig = binding_perturbation_bar_grid(
        _grid_bar_panels(),
        ["b1", "b2"],
        ["p1", "p2"],
        ["kang", "mindel"],
        {"b1": "Binding 1", "b2": "Binding 2"},
        {"p1": "P1", "p2": "P2"},
        {"kang": "Kang", "mindel": "Mindel"},
        {"kang": "#377EB8", "mindel": "#4DAF4A"},
    )
    labels = {(t.x[0], t.text[0]) for t in fig.data}
    assert labels == {("Kang", "5/10"), ("Mindel", "3/10"), ("Kang", "2/8")}


def test_bar_grid_skips_missing_pair() -> None:
    """A missing/empty (b_db, p_db) entry produces no bars rather than raising."""
    from tfbpshiny.modules.figures.plots import binding_perturbation_bar_grid

    panels = {
        ("b1", "p1"): pd.DataFrame(
            {
                "box_key": ["kang"],
                "n_significant": [1],
                "n_shared": [10],
                "fraction_significant": [0.1],
            }
        ),
        ("b1", "p2"): pd.DataFrame(
            columns=["box_key", "n_significant", "n_shared", "fraction_significant"]
        ),
    }
    fig = binding_perturbation_bar_grid(
        panels,
        ["b1", "b2"],
        ["p1", "p2"],
        ["kang", "mindel"],
        {"b1": "Binding 1", "b2": "Binding 2"},
        {"p1": "P1", "p2": "P2"},
        {"kang": "Kang", "mindel": "Mindel"},
        {"kang": "#377EB8", "mindel": "#4DAF4A"},
    )
    assert len(fig.data) == 1
