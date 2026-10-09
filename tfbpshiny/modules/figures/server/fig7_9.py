"""
Figures 7, 8, 9: promoter-definition and method comparisons as box/bar grids.

These port what the Comparison module's "Compare Promoter Definitions" and "Compare
Analysis Methods" tabs already show as a table of medians, but as the actual
distribution across TFs, faceted by binding dataset (rows) AND perturbation dataset
(columns) at once -- the first two-axis grid in this module (every other figure facets
on only one axis, folding the other into a trace loop within each panel). See
``binding_perturbation_box_grid``.

"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import pandas as pd
from shiny import reactive, render, ui

from tfbpshiny.components import empty_state
from tfbpshiny.datasets import PROMOTER_ENRICHMENT_500BP, figure_method
from tfbpshiny.materialize.comparison.method_promoter_model import (
    pair_methods_on_regulators,
)
from tfbpshiny.modules.figures.plots import (
    FIG7_RESPONSE_Y,
    binding_perturbation_bar_grid,
    binding_perturbation_box_grid,
)
from tfbpshiny.modules.figures.queries import (
    METHOD_COMPARISON_BINDING,
    METHOD_LEVELS,
    PR_ORDER,
    PROMOTER_SET_LEVELS,
    fetch_dto_significance,
    fetch_dto_significance_for_universe,
    fetch_topn_percent_responsive,
    regulator_intersection,
    resolve_promoter_variant,
)
from tfbpshiny.modules.figures.server.context import FiguresContext
from tfbpshiny.modules.figures.server.shared import Shared
from tfbpshiny.utils.figure import figure_html
from tfbpshiny.utils.perf import perf

Panels = dict[tuple[str, str], pd.DataFrame]


def register_fig7_9(
    input: Any, session: Any, ctx: FiguresContext, shared: Shared
) -> None:
    """
    Register the outputs of figures 7, 8 and 9.

    :param input: Shiny input object of the figures module.
    :param session: Module session.
    :param ctx: Per-session context.
    :param shared: Shared reactives.

    """
    conn = ctx.conn

    def _resolve_variant_cells(
        binding_primaries: tuple[str, ...], combos: list[tuple[str, str, str]]
    ) -> dict[str, tuple[str, str]]:
        """
        ``variant db_name -> (binding_primary, box_key)``, for every combination that
        resolves to a real dataset. Keyed by variant because the plot queries take
        variant db_names, while the grid needs the primary (row) and box_key (box)
        each variant's data belongs to.

        :param binding_primaries: Assay primaries to resolve variants for.
        :param combos: ``(promoter_set_id, method_id, box_key)`` tuples defining the
            box axis -- figures 7/8 vary promoter set (method fixed), figure 9 varies
            method (promoter set fixed at 500bp).

        """
        variant_cell: dict[str, tuple[str, str]] = {}
        for b_primary in binding_primaries:
            for promoter_set_id, method_id, box_key in combos:
                variant = resolve_promoter_variant(
                    conn, b_primary, promoter_set_id, method_id
                )
                if variant:
                    variant_cell[variant] = (b_primary, box_key)
        return variant_cell

    def _fig78_variant_cells() -> dict[str, tuple[str, str]]:
        """
        Figures 7/8's cells: one variant per (assay, promoter set), using each assay's
        :func:`~tfbpshiny.datasets.figure_method` (peak calling for Rossi and ChEC-seq,
        promoter enrichment for Calling Cards, which has no peak-calling arm).

        """
        cells: dict[str, tuple[str, str]] = {}
        for b_primary in PROMOTER_ENRICHMENT_500BP:
            method = figure_method(b_primary)
            cells.update(
                _resolve_variant_cells(
                    (b_primary,), [(ps, method, ps) for ps in PROMOTER_SET_LEVELS]
                )
            )
        return cells

    def _topn_box_panels(
        variant_cell: dict[str, tuple[str, str]],
        tf_sets: dict[str, list[str]],
    ) -> Panels:
        """
        Top-N percent responsive per regulator, reshaped to ``(binding_primary, pr_db)
        -> [box_key, value]`` for :func:`binding_perturbation_box_grid`.

        One query per perturbation dataset covers every variant at once --
        ``fetch_topn_percent_responsive`` already accepts a list of binding_dbs.

        """
        filters = ctx.dataset_filters()
        preset = shared.read_scoring()
        top_n = shared.read_top_n()
        variants = list(variant_cell)
        if not variants:
            return {}
        out_parts: dict[tuple[str, str], list[pd.DataFrame]] = defaultdict(list)
        for p_db in PR_ORDER:
            regs = tf_sets.get(p_db, [])
            if not regs:
                continue
            df = fetch_topn_percent_responsive(
                conn, variants, p_db, regs, top_n, filters, preset
            )
            if df.empty:
                continue
            for binding_db, sub in df.groupby("binding_db"):
                b_primary, box_key = variant_cell[binding_db]
                out_parts[(b_primary, p_db)].append(
                    pd.DataFrame(
                        {
                            "box_key": box_key,
                            "value": sub["percent_responsive"].to_numpy(),
                        }
                    )
                )
        return {
            key: pd.concat(parts, ignore_index=True) for key, parts in out_parts.items()
        }

    def _fig9_topn_box_panels(
        variant_cell: dict[str, tuple[str, str]],
        tf_sets: dict[str, list[str]],
    ) -> Panels:
        """
        Figure 9 top grid's per-box data: like :func:`_topn_box_panels`, but keeps a
        regulator only where promoter enrichment AND peak calling both have a row (see
        :func:`~tfbpshiny.materialize.comparison.method_promoter_model.

        pair_methods_on_regulators`), so the two boxes describe the same TFs. A TF with
        no usable peak-calling list is dropped from both boxes, not scored as zero.
        ``variant_cell``'s box_key is the method id here (:data:`METHOD_LEVELS`), which
        doubles as the pairing's method column.

        """
        filters = ctx.dataset_filters()
        preset = shared.read_scoring()
        top_n = shared.read_top_n()
        variants = list(variant_cell)
        if not variants:
            return {}
        out_parts: dict[tuple[str, str], list[pd.DataFrame]] = defaultdict(list)
        for p_db in PR_ORDER:
            regs = tf_sets.get(p_db, [])
            if not regs:
                continue
            df = fetch_topn_percent_responsive(
                conn, variants, p_db, regs, top_n, filters, preset
            )
            if df.empty:
                continue
            df = df.copy()
            df["binding_primary"] = df["binding_db"].map(lambda b: variant_cell[b][0])
            df["method"] = df["binding_db"].map(lambda b: variant_cell[b][1])
            df = pair_methods_on_regulators(df, group_cols=["binding_primary"])
            for b_primary, sub in df.groupby("binding_primary"):
                out_parts[(b_primary, p_db)].append(
                    pd.DataFrame(
                        {
                            "box_key": sub["method"].to_numpy(),
                            "value": sub["percent_responsive"].to_numpy(),
                        }
                    )
                )
        return {
            key: pd.concat(parts, ignore_index=True) for key, parts in out_parts.items()
        }

    def _dto_bar_panels(variant_cell: dict[str, tuple[str, str]]) -> Panels:
        """
        DTO significance fraction per regulator population, reshaped the same way as
        :func:`_topn_box_panels`.

        One ``fetch_dto_significance`` call per (variant,
        perturbation dataset) pair -- reusing figure 4's own query function, called
        per-variant instead of over the fixed :data:`DTO_BINDING_ORDER` list.

        """
        if not ctx.schema_current:
            return {}
        out_parts: dict[tuple[str, str], list[pd.DataFrame]] = defaultdict(list)
        for variant, (b_primary, box_key) in variant_cell.items():
            for p_db in PR_ORDER:
                df = fetch_dto_significance(conn, [variant], [p_db])
                if df.empty:
                    continue
                row = df.iloc[0]
                out_parts[(b_primary, p_db)].append(
                    pd.DataFrame(
                        {
                            "box_key": [box_key],
                            "n_significant": [int(row["n_significant"])],
                            "n_shared": [int(row["n_shared"])],
                            "fraction_significant": [
                                float(row["fraction_significant"])
                            ],
                        }
                    )
                )
        return {
            key: pd.concat(parts, ignore_index=True) for key, parts in out_parts.items()
        }

    def _fig9_dto_bar_panels(variant_cell: dict[str, tuple[str, str]]) -> Panels:
        """
        Figure 9 bottom grid's per-bar data: like :func:`_dto_bar_panels`, but shares
        one 3-way-intersected regulator universe (promoter_enrichment regs x
        peak_calling regs x perturbation regs) between each sibling pair's two bars,
        instead of each bar computing its own pairwise intersection with the
        perturbation dataset.

        DTO significance is pre-computed entirely externally, so a
        regulator peak_calling never called a peak for has no value to report -- as in
        the top grid, the fair comparison is to hold both bars to the same (smaller)
        shared universe.
        :func:`_dto_bar_panels` (figure 8) is untouched -- it never varies method, so
        this asymmetry does not apply there.

        """
        if not ctx.schema_current:
            return {}
        by_primary: dict[str, dict[str, str]] = defaultdict(dict)
        for variant, (b_primary, method) in variant_cell.items():
            by_primary[b_primary][method] = variant

        out_parts: dict[tuple[str, str], list[pd.DataFrame]] = defaultdict(list)
        for b_primary, methods in by_primary.items():
            pe_variant = methods.get("promoter_enrichment")
            pc_variant = methods.get("peak_calling")
            if not pe_variant or not pc_variant:
                continue
            for p_db in PR_ORDER:
                universe = set(
                    regulator_intersection(conn, [pe_variant, pc_variant, p_db])
                )
                n_shared = len(universe)
                if n_shared == 0:
                    continue
                for method, variant in (
                    ("promoter_enrichment", pe_variant),
                    ("peak_calling", pc_variant),
                ):
                    stats = fetch_dto_significance_for_universe(
                        conn, variant, p_db, universe
                    )
                    out_parts[(b_primary, p_db)].append(
                        pd.DataFrame(
                            {
                                "box_key": [method],
                                "n_significant": [stats["n_significant"]],
                                "n_shared": [n_shared],
                                "fraction_significant": [
                                    stats["n_significant"] / n_shared
                                ],
                            }
                        )
                    )
        return {
            key: pd.concat(parts, ignore_index=True) for key, parts in out_parts.items()
        }

    @reactive.calc
    def _fig7_panels() -> Panels:
        """
        Figure 7's data: top-N percent responsive, one box per promoter set.

        :trigger: ``dataset_filters`` / ``input.scoring`` / ``input.box_top_n``.

        """
        with perf(session.id, "figures.workspace", "_fig7_panels", kind="data"):
            variant_cell = _fig78_variant_cells()
            return _topn_box_panels(variant_cell, shared.fig7_tf_sets())

    @reactive.calc
    def _fig8_panels() -> Panels:
        """
        Figure 8's data: % of shared TFs that are DTO-significant, one bar per promoter
        set.

        :trigger: none beyond the database.

        """
        with perf(session.id, "figures.workspace", "_fig8_panels", kind="data"):
            variant_cell = _fig78_variant_cells()
            return _dto_bar_panels(variant_cell)

    @reactive.calc
    def _fig9_top_panels() -> Panels:
        """
        Figure 9's top grid: top-N percent responsive, one box per method, at 500bp.

        :trigger: ``dataset_filters`` / ``input.scoring`` / ``input.box_top_n``.

        """
        with perf(session.id, "figures.workspace", "_fig9_top_panels", kind="data"):
            combos = [("500bp", m, m) for m in METHOD_LEVELS]
            variant_cell = _resolve_variant_cells(METHOD_COMPARISON_BINDING, combos)
            return _fig9_topn_box_panels(variant_cell, shared.fig9_tf_sets())

    @reactive.calc
    def _fig9_bottom_panels() -> Panels:
        """
        Figure 9's bottom grid: % of shared TFs that are DTO-significant, one bar per
        method, at 500bp.

        :trigger: none beyond the database.

        """
        with perf(session.id, "figures.workspace", "_fig9_bottom_panels", kind="data"):
            combos = [("500bp", m, m) for m in METHOD_LEVELS]
            variant_cell = _resolve_variant_cells(METHOD_COMPARISON_BINDING, combos)
            return _fig9_dto_bar_panels(variant_cell)

    @render.ui
    def fig_promoter_boxes() -> ui.Tag:
        """
        Figure 7: top-N percent responsive across TFs, one box per promoter set,
        faceted by binding dataset (rows) and perturbation dataset (columns).

        :trigger: ``_fig7_panels``.

        """
        with perf(session.id, "figures.workspace", "fig_promoter_boxes"):
            panels = _fig7_panels()
            if not panels:
                return empty_state(ui.p("No data for these datasets."))
            fig = binding_perturbation_box_grid(
                panels,
                list(PROMOTER_ENRICHMENT_500BP),
                list(PR_ORDER),
                list(PROMOTER_SET_LEVELS),
                ctx.labels,
                ctx.labels,
                ctx.promoter_set_labels,
                ctx.promoter_set_colors,
                y_title=f"% responsive in top {shared.read_top_n()}",
                y_range=FIG7_RESPONSE_Y,
            )
            return ui.div(figure_html(fig, filename="fig7_promoter_boxes"))

    @render.ui
    def fig_dto_significance_grid() -> ui.Tag:
        """
        Figure 8: % of shared TFs that are DTO-significant, one bar per promoter set,
        same grid as figure 7.

        :trigger: ``_fig8_panels``.

        """
        if not ctx.schema_current:
            return shared.dto_missing()
        with perf(session.id, "figures.workspace", "fig_dto_significance_grid"):
            panels = _fig8_panels()
            if not panels:
                return empty_state(ui.p("No DTO results."))
            fig = binding_perturbation_bar_grid(
                panels,
                list(PROMOTER_ENRICHMENT_500BP),
                list(PR_ORDER),
                list(PROMOTER_SET_LEVELS),
                ctx.labels,
                ctx.labels,
                ctx.promoter_set_labels,
                ctx.promoter_set_colors,
                y_title="% of shared TFs (DTO p < 0.01)",
            )
            return ui.div(figure_html(fig, filename="fig8_dto_bars"))

    @render.ui
    def fig_method_boxes() -> ui.Tag:
        """
        Figure 9: peak calling vs. promoter enrichment at the 500bp promoter set,
        same grid shape as figures 7/8 but restricted to Rossi and ChEC-seq (Calling
        Cards has no peak-calling arm). Top grid: top-N percent responsive. Bottom
        grid: % of shared TFs that are DTO-significant, the same metric as figure 8.

        :trigger: ``_fig9_top_panels`` / ``_fig9_bottom_panels``.

        """
        with perf(session.id, "figures.workspace", "fig_method_boxes"):
            blocks: list[ui.Tag] = []

            top_panels = _fig9_top_panels()
            if top_panels:
                top_fig = binding_perturbation_box_grid(
                    top_panels,
                    list(METHOD_COMPARISON_BINDING),
                    list(PR_ORDER),
                    list(METHOD_LEVELS),
                    ctx.labels,
                    ctx.labels,
                    ctx.method_labels,
                    ctx.method_colors,
                    y_title=f"% responsive in top {shared.read_top_n()}",
                    y_range=FIG7_RESPONSE_Y,
                )
                blocks.append(figure_html(top_fig, filename="fig9_topn_boxes"))
            else:
                blocks.append(empty_state(ui.p("No data for these datasets.")))

            if not ctx.schema_current:
                blocks.append(shared.dto_missing())
            else:
                bottom_panels = _fig9_bottom_panels()
                if bottom_panels:
                    bottom_fig = binding_perturbation_bar_grid(
                        bottom_panels,
                        list(METHOD_COMPARISON_BINDING),
                        list(PR_ORDER),
                        list(METHOD_LEVELS),
                        ctx.labels,
                        ctx.labels,
                        ctx.method_labels,
                        ctx.method_colors,
                        y_title="% of shared TFs (DTO p < 0.01)",
                    )
                    blocks.append(figure_html(bottom_fig, filename="fig9_dto_bars"))
                else:
                    blocks.append(empty_state(ui.p("No DTO results.")))
            return ui.div(*blocks)


__all__ = ["register_fig7_9"]
