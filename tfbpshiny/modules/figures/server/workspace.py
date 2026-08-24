"""Workspace server for the Figures page."""

from __future__ import annotations

from logging import Logger
from typing import Any

import duckdb
import pandas as pd
from shiny import module, reactive, render, ui

from tfbpshiny.components import scroll_row, sidebar_label
from tfbpshiny.modules.figures.plots import (
    agreement_box_figure,
    agreement_curve_figure,
    authors_bound_grid,
    dto_significance_bars,
    dto_venn_figure,
    percent_responsive_boxes,
    rank_response_facet,
    rank_response_figure,
)
from tfbpshiny.modules.figures.queries import (
    AGREEMENT_DEFAULT_BINDING,
    AGREEMENT_DEFAULT_PERTURBATION,
    AGREEMENT_PAIR_WARN,
    AUTHORS_PEAK_BINDING,
    BINDING_ORDER,
    DTO_BINDING_ORDER,
    PR_ORDER,
    TOP_N_ALL,
    agreement_dataset_choices,
    dataset_labels,
    fetch_agreement,
    fetch_authors_bound,
    fetch_dto_significance,
    fetch_dto_significant_sets,
    fetch_rank_response,
    fetch_topn_percent_responsive,
    has_top_n,
    regulator_intersection,
    table_exists,
    weighted_agreement,
)
from tfbpshiny.utils.figure import figure_html, matplotlib_svg_html
from tfbpshiny.utils.perf import perf, reset_render_counts
from tfbpshiny.utils.vdb_init import get_regulator_display_name

#: Width of one panel in the three-across figure rows.
_PANEL_WIDTH = "min-width: 420px; flex: 1 1 420px;"


@module.server
def figures_workspace_server(
    input: Any,
    output: Any,
    session: Any,
    dataset_filters: reactive.Value[dict[str, Any]],
    conn: duckdb.DuckDBPyConnection,
    logger: Logger,
) -> None:
    """
    Render the publication figures.

    Unlike the analysis pages, the figures are drawn over fixed dataset sets rather than
    the sidebar's active selection -- each figure is defined by an intersection of
    specific datasets, so letting the selection change them would change what the figure
    means. Per-dataset *sample* filters are honoured, since those decide which samples
    represent a dataset (e.g. the Hackett timepoint).

    :param dataset_filters: Reactive per-dataset sample filter specs.
    :param conn: Read-only DuckDB connection to the materialized database.
    :param logger: Application logger.

    """
    session.on_flush(lambda: reset_render_counts(session.id))

    _labels = dataset_labels(conn)

    _reg_df = get_regulator_display_name(conn)
    _reg_labels: dict[str, str] = {}
    for _, row in _reg_df.iterrows():
        tag = str(row["regulator_locus_tag"])
        sym = str(row.get("regulator_symbol", ""))
        _reg_labels[tag] = f"{sym} ({tag})" if sym and sym not in ("nan", tag) else tag

    # Availability of the DTO tables decides whether figures 4 and 5 can render.
    _dto_available = (
        conn.execute(
            "SELECT count(*) FROM information_schema.tables"
            " WHERE table_name IN ('dto', 'sample_regulator')"
        ).fetchone()[0]
        == 2
    )

    # The whole-bound-set rows and the agreement table only exist in databases
    # built after the Phase 2 materialization additions.
    _authors_bound_available = has_top_n(conn, TOP_N_ALL)
    _agreement_available = table_exists(conn, "topn_agreement")
    for name, ok in (
        ("authors'-binding-threshold rows", _authors_bound_available),
        ("topn_agreement", _agreement_available),
    ):
        if not ok:
            logger.warning(
                "figures: %s missing from the database; the figures that need it"
                " will explain themselves rather than render",
                name,
            )

    def _needs_rebuild(what: str) -> ui.Tag:
        """Empty state for a figure whose data predates the current materializer."""
        return ui.div(
            {"class": "empty-state"},
            ui.p(
                ui.strong(f"{what} is not in this database."),
                " Rebuild with ",
                ui.tags.code("tfbpshiny materialize --preset Stringent"),
                " to enable this figure.",
            ),
        )

    # ------------------------------------------------------------------
    # Shared reactive data
    # ------------------------------------------------------------------

    @reactive.calc
    def _tf_sets() -> dict[str, list[str]]:
        """
        Regulators in (all four binding datasets) ∩ each perturbation dataset.

        :trigger: none -- depends only on the database, so computed once per session.

        """
        return {
            p: regulator_intersection(conn, list(BINDING_ORDER) + [p]) for p in PR_ORDER
        }

    @reactive.calc
    def _featured_tfs() -> list[str]:
        """Regulators present in all four binding datasets and all three PR datasets."""
        return regulator_intersection(conn, list(BINDING_ORDER) + list(PR_ORDER))

    @reactive.calc
    def _rank_response() -> dict[str, pd.DataFrame]:
        """
        Rank-response rows per perturbation dataset.

        :trigger: ``dataset_filters`` -- sample filters change which samples the
            median is taken over.
        :trigger: ``input.scoring`` -- selects which responsiveness definition to
            read; the table stores several per key.

        """
        filters = dataset_filters()
        sets = _tf_sets()
        preset = _read_scoring()
        with perf(session.id, "figures.workspace", "_rank_response", kind="data"):
            return {
                p: fetch_rank_response(
                    conn,
                    list(BINDING_ORDER),
                    p,
                    sets.get(p, []),
                    filters,
                    preset,
                )
                for p in PR_ORDER
            }

    def _read_scoring() -> str:
        """
        The selected responsiveness preset.

        Falls back to Relaxed, which every build has.

        """
        try:
            return str(input.scoring())
        except Exception:
            return "Relaxed"

    def _read_top_n() -> int:
        try:
            return int(input.box_top_n())
        except Exception:
            return 25

    # ------------------------------------------------------------------
    # Sidebar
    # ------------------------------------------------------------------

    @render.ui
    def tf_selector() -> ui.Tag:
        """
        Selector for the TF featured in figure 1.

        :trigger: ``_featured_tfs``.

        """
        tfs = _featured_tfs()
        if not tfs:
            return ui.span()
        return ui.div(
            ui.tags.label("Featured TF", class_="form-label mt-3 mb-1"),
            ui.input_select(
                "featured_tf",
                label=None,
                choices={t: _reg_labels.get(t, t) for t in tfs},
                selected=tfs[0],
            ),
        )

    @render.ui
    def figure_status() -> ui.Tag:
        """
        Summary of the TF sets the figures are drawn over.

        :trigger: ``_tf_sets``.

        """
        sets = _tf_sets()
        parts = ", ".join(
            f"{_labels.get(p, p)}: {len(sets.get(p, []))}" for p in PR_ORDER
        )
        note = (
            ""
            if _dto_available
            else " DTO tables are absent from this database, so figures 4 and 5"
            " cannot be drawn -- rebuild with `tfbpshiny materialize`."
        )
        return ui.div(
            {"class": "sidebar-text"},
            ui.p(
                ui.strong("TFs per figure: "),
                f"all four binding datasets intersected with each perturbation"
                f" dataset -- {parts}."
                f" Figure 1's featured TF is drawn from the "
                f"{len(_featured_tfs())} TFs present in all seven datasets.{note}",
            ),
        )

    # ------------------------------------------------------------------
    # Figure 1
    # ------------------------------------------------------------------

    @render.ui
    def fig_rank_response() -> ui.Tag:
        """
        Rank-response curves for the featured TF, one panel per PR dataset.

        :trigger: ``_rank_response`` / ``input.featured_tf``.

        """
        try:
            tf = str(input.featured_tf())
        except Exception:
            return ui.span()
        data = _rank_response()
        with perf(session.id, "figures.workspace", "fig_rank_response"):
            panels = []
            for p in PR_ORDER:
                df = data.get(p, pd.DataFrame())
                if df.empty:
                    continue
                sub = df[df["regulator_locus_tag"] == tf]
                if sub.empty:
                    continue
                fig = rank_response_figure(
                    sub,
                    _labels,
                    list(BINDING_ORDER),
                    title=f"{_labels.get(p, p)} — {_reg_labels.get(tf, tf)}",
                )
                panels.append(
                    ui.div(
                        figure_html(fig, filename=f"fig1_rank_response_{p}_{tf}"),
                        style=_PANEL_WIDTH,
                    )
                )
            if not panels:
                return ui.div(
                    {"class": "empty-state"},
                    ui.p("No rank-response data for the selected TF."),
                )
            return scroll_row(*panels, gap="lg")

    @render.ui
    def fig_rank_response_facets() -> ui.Tag:
        """
        Small-multiples grid over every TF in the intersection.

        :trigger: ``input.show_facets`` / ``_rank_response``.

        """
        try:
            if not bool(input.show_facets()):
                return ui.span()
        except Exception:
            return ui.span()
        data = _rank_response()
        sets = _tf_sets()
        with perf(session.id, "figures.workspace", "fig_rank_response_facets"):
            blocks = []
            for p in PR_ORDER:
                df = data.get(p, pd.DataFrame())
                tfs = sets.get(p, [])
                if df.empty or not tfs:
                    continue
                fig = rank_response_facet(
                    df, _labels, list(BINDING_ORDER), tfs, _reg_labels
                )
                blocks.append(
                    ui.div(
                        ui.h4(
                            f"{_labels.get(p, p)} — all {len(tfs)} TFs",
                            style="margin-top: 1.5rem;",
                        ),
                        figure_html(fig, filename=f"fig1_rank_response_all_{p}"),
                    )
                )
            if not blocks:
                return ui.span()
            return ui.div(*blocks)

    # ------------------------------------------------------------------
    # Figure 2
    # ------------------------------------------------------------------

    @render.ui
    def fig_topn_boxes() -> ui.Tag:
        """
        Percent-responsive box plots at the selected top-N cutoff.

        :trigger: ``dataset_filters`` / ``input.box_top_n``.

        """
        filters = dataset_filters()
        sets = _tf_sets()
        top_n = _read_top_n()
        preset = _read_scoring()
        with perf(session.id, "figures.workspace", "fig_topn_boxes"):
            panels = []
            for p in PR_ORDER:
                tfs = sets.get(p, [])
                if not tfs:
                    continue
                df = fetch_topn_percent_responsive(
                    conn, list(BINDING_ORDER), p, tfs, top_n, filters, preset
                )
                if df.empty:
                    continue
                fig = percent_responsive_boxes(
                    df,
                    _labels,
                    list(BINDING_ORDER),
                    title=(
                        f"{_labels.get(p, p)}  (n={len(tfs)} TFs,"
                        f" {preset.lower()} criteria)"
                    ),
                    y_title=f"% responsive in top {top_n}",
                )
                panels.append(
                    ui.div(
                        figure_html(fig, filename=f"fig2_top{top_n}_responsive_{p}"),
                        style=_PANEL_WIDTH,
                    )
                )
            if not panels:
                return ui.div(
                    {"class": "empty-state"}, ui.p("No data for these datasets.")
                )
            return scroll_row(*panels, gap="lg")

    # ------------------------------------------------------------------
    # Figures 4 and 5
    # ------------------------------------------------------------------

    def _dto_missing() -> ui.Tag:
        return ui.div(
            {"class": "empty-state"},
            ui.p(
                ui.strong("DTO results are not in this database."),
                " Rebuild with ",
                ui.tags.code("tfbpshiny materialize"),
                " to draw this figure.",
            ),
        )

    @render.ui
    def fig_dto_bars() -> ui.Tag:
        """
        DTO-significant counts and fractions.

        :trigger: none beyond the database -- DTO is not sample-filtered here.

        """
        if not _dto_available:
            return _dto_missing()
        with perf(session.id, "figures.workspace", "fig_dto_bars"):
            df = fetch_dto_significance(conn, list(DTO_BINDING_ORDER), list(PR_ORDER))
            if df.empty:
                return ui.div({"class": "empty-state"}, ui.p("No DTO results."))
            fig = dto_significance_bars(
                df, _labels, list(DTO_BINDING_ORDER), list(PR_ORDER)
            )
            return ui.div(
                figure_html(fig, filename="fig4_dto_significance"),
                ui.p(
                    {"class": "sidebar-text"},
                    ui.tags.em(
                        "ChIP-chip is absent because the upstream DTO analysis"
                        " does not cover it."
                    ),
                ),
            )

    @render.ui
    def fig_dto_venn() -> ui.Tag:
        """
        Venn diagrams of DTO significance across the three binding datasets.

        :trigger: none beyond the database.

        """
        if not _dto_available:
            return _dto_missing()
        with perf(session.id, "figures.workspace", "fig_dto_venn"):
            panels = []
            for p in PR_ORDER:
                sets = fetch_dto_significant_sets(conn, list(DTO_BINDING_ORDER), p)
                if not any(sets.values()):
                    continue
                mpl_fig = dto_venn_figure(
                    sets,
                    _labels,
                    list(DTO_BINDING_ORDER),
                    title=_labels.get(p, p),
                )
                panels.append(
                    ui.div(
                        matplotlib_svg_html(
                            mpl_fig,
                            alt=f"DTO significance Venn, {p}",
                            filename=f"fig5_dto_venn_{p}",
                        ),
                        style="min-width: 380px; flex: 1 1 380px;",
                    )
                )
            if not panels:
                return ui.div({"class": "empty-state"}, ui.p("No DTO results."))
            return scroll_row(*panels, gap="lg")

    # ------------------------------------------------------------------
    # Figure 3 -- authors' binding thresholds
    # ------------------------------------------------------------------

    @render.ui
    def fig_authors_bound() -> ui.Tag:
        """
        Response rate and bound-set size over the authors' bound targets.

        :trigger: ``dataset_filters``.

        """
        if not _authors_bound_available:
            return _needs_rebuild("The authors'-binding-threshold data")
        filters = dataset_filters()
        preset = _read_scoring()
        with perf(session.id, "figures.workspace", "fig_authors_bound"):
            frames = {
                p: fetch_authors_bound(
                    conn, list(AUTHORS_PEAK_BINDING), p, filters, preset
                )
                for p in PR_ORDER
            }
            frames = {k: v for k, v in frames.items() if not v.empty}
            if not frames:
                return ui.div(
                    {"class": "empty-state"}, ui.p("No authors'-threshold rows.")
                )
            fig = authors_bound_grid(
                frames, _labels, list(AUTHORS_PEAK_BINDING), list(PR_ORDER)
            )
            return ui.div(figure_html(fig, filename="fig3_authors_bound"))

    # ------------------------------------------------------------------
    # Figure 6 -- agreement between datasets
    # ------------------------------------------------------------------

    # Selectable datasets, read once: dataset_registry does not change per session.
    _agreement_choices: dict[str, dict[str, str]] = (
        {
            ctype: agreement_dataset_choices(conn, ctype)
            for ctype in ("binding", "perturbation")
        }
        if _agreement_available
        else {"binding": {}, "perturbation": {}}
    )
    _agreement_defaults: dict[str, tuple[str, ...]] = {
        "binding": AGREEMENT_DEFAULT_BINDING,
        "perturbation": AGREEMENT_DEFAULT_PERTURBATION,
    }

    @render.ui
    def agreement_dataset_picker() -> ui.Tag:
        """
        Checkbox groups choosing which datasets figure 6 compares.

        Rendered rather than static so the choices come from ``dataset_registry``
        instead of a hand-maintained list that could drift from the database.

        :trigger: none -- the registry is fixed for the session.

        """
        groups = []
        for ctype, heading in (
            ("binding", "Binding"),
            ("perturbation", "Perturbation"),
        ):
            choices = _agreement_choices.get(ctype, {})
            if not choices:
                continue
            selected = [d for d in _agreement_defaults[ctype] if d in choices]
            groups.append(
                ui.div(
                    sidebar_label(heading),
                    ui.input_checkbox_group(
                        f"agreement_{ctype}",
                        label=None,
                        choices=choices,
                        selected=selected,
                    ),
                    style="flex: 1 1 260px;",
                )
            )
        if not groups:
            return ui.div()
        return ui.div(
            *groups,
            style="display: flex; gap: 2rem; flex-wrap: wrap;",
        )

    def _agreement_selection(ctype: str) -> list[str]:
        """
        Datasets selected for one panel, falling back to the default.

        :param ctype: ``'binding'`` or ``'perturbation'``.
        :returns: db_names, empty when fewer than two are selected.

        """
        choices = _agreement_choices.get(ctype, {})
        try:
            chosen = list(getattr(input, f"agreement_{ctype}")() or [])
        except Exception:
            chosen = []
        if not chosen:
            chosen = list(_agreement_defaults[ctype])
        return [d for d in chosen if d in choices]

    @reactive.calc
    def _agreement() -> dict[str, pd.DataFrame]:
        """
        Overlap enrichment for binding-vs-binding and perturbation-vs-perturbation.

        :trigger: ``input.agreement_binding`` / ``input.agreement_perturbation`` --
            every pair among the selected datasets is drawn.

        """
        if not _agreement_available:
            return {}
        with perf(session.id, "figures.workspace", "_agreement", kind="data"):
            out: dict[str, pd.DataFrame] = {}
            for ctype in ("binding", "perturbation"):
                selected = _agreement_selection(ctype)
                n_pairs = len(selected) * (len(selected) - 1) // 2
                if n_pairs > AGREEMENT_PAIR_WARN:
                    logger.warning(
                        "figures: %s agreement has %d dataset pairs selected"
                        " (%d datasets); above %d the lines and boxes overlap"
                        " too much to separate",
                        ctype,
                        n_pairs,
                        len(selected),
                        AGREEMENT_PAIR_WARN,
                    )
                out[ctype] = fetch_agreement(conn, ctype, selected)
            return out

    def _agreement_empty_note(ctype: str, heading: str) -> ui.Tag | None:
        """
        Explain why one panel of figure 6 drew nothing.

        Emitted per panel rather than for the figure as a whole: the perturbation
        datasets have no promoter variants and so were always materialized, and its
        panel rendering would otherwise hide the binding panel's absence entirely.

        :param ctype: ``'binding'`` or ``'perturbation'``.
        :param heading: Panel heading to name in the message.
        :returns: An empty-state div, or ``None`` when nothing needs saying.

        """
        selected = _agreement_selection(ctype)
        if len(selected) < 2:
            return ui.div(
                {"class": "empty-state"},
                ui.p(f"{heading}: select at least two datasets to compare."),
            )
        return ui.div(
            {"class": "empty-state"},
            ui.p(
                ui.strong(f"{heading}: no overlap rows for these datasets."),
                " Databases built before figure 6 gained its dataset selector"
                " cover only the four primary binding datasets. Rebuild with ",
                ui.tags.code("tfbpshiny materialize"),
                " to compare promoter definitions and calling methods.",
            ),
        )

    @render.ui
    def fig_agreement() -> ui.Tag:
        """
        Overlap enrichment vs N for the featured TF, and its weighted summary.

        :trigger: ``_agreement`` / ``input.featured_tf``.

        """
        if not _agreement_available:
            return _needs_rebuild("The dataset-agreement table")
        try:
            tf = str(input.featured_tf())
        except Exception:
            tf = ""
        data = _agreement()
        with perf(session.id, "figures.workspace", "fig_agreement"):
            blocks = []
            for ctype, heading in (
                ("binding", "Binding vs. binding"),
                ("perturbation", "Perturbation vs. perturbation"),
            ):
                df = data.get(ctype, pd.DataFrame())
                if df.empty:
                    note = _agreement_empty_note(ctype, heading)
                    if note is not None:
                        blocks.append(note)
                    continue
                curve_src = df[df["regulator_locus_tag"] == tf] if tf else df
                panels = []
                if not curve_src.empty:
                    panels.append(
                        ui.div(
                            figure_html(
                                agreement_curve_figure(
                                    curve_src,
                                    title=(f"{heading} — {_reg_labels.get(tf, tf)}"),
                                ),
                                filename=f"fig6_agreement_curve_{ctype}_{tf}",
                            ),
                            style="flex: 1 1 0; min-width: 520px;",
                        )
                    )
                weighted = weighted_agreement(df)
                if not weighted.empty:
                    panels.append(
                        ui.div(
                            figure_html(
                                agreement_box_figure(
                                    weighted,
                                    title=f"{heading} — all TFs",
                                ),
                                filename=f"fig6_agreement_weighted_{ctype}",
                            ),
                            style="flex: 1 1 0; min-width: 520px;",
                        )
                    )
                if panels:
                    blocks.append(
                        ui.div(
                            {
                                "style": (
                                    "display: flex; gap: 1.5rem;"
                                    " align-items: flex-start; flex-wrap: wrap;"
                                )
                            },
                            *panels,
                        )
                    )
            if not blocks:
                return ui.div({"class": "empty-state"}, ui.p("No agreement results."))
            return ui.div(*blocks)


__all__ = ["figures_workspace_server"]
