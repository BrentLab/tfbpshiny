"""Workspace server for the Figures page."""

from __future__ import annotations

from collections import defaultdict
from logging import Logger
from typing import Any

import duckdb
import pandas as pd
from shiny import module, reactive, render, ui

from tfbpshiny.components import scroll_row, sidebar_label
from tfbpshiny.materialize.comparison.method_promoter_model import (
    pair_methods_on_regulators,
)
from tfbpshiny.modules.figures.plots import (
    DTO_VENN_LAYOUT_DEFAULT,
    FIG7_RESPONSE_Y,
    agreement_box_figure,
    agreement_curve_figure,
    authors_bound_grid,
    binding_perturbation_bar_grid,
    binding_perturbation_box_grid,
    dto_significance_bars,
    dto_venn_figure,
    percent_responsive_boxes,
    rank_response_facet,
    rank_response_figure,
    shared_targets_box_figure,
)
from tfbpshiny.modules.figures.queries import (
    AGREEMENT_DEFAULT_BINDING,
    AGREEMENT_DEFAULT_PERTURBATION,
    AGREEMENT_HALF_LIFE_DEFAULT,
    AGREEMENT_PAIR_WARN,
    AUTHORS_PEAK_BINDING,
    BINDING_ORDER,
    DTO_BINDING_ORDER,
    METHOD_COMPARISON_BINDING,
    METHOD_LEVELS,
    PR_ORDER,
    PROMOTER_SET_LEVELS,
    TOP_N_ALL,
    agreement_dataset_choices,
    dataset_labels,
    fetch_agreement,
    fetch_authors_bound,
    fetch_dto_significance,
    fetch_dto_significance_for_universe,
    fetch_dto_significant_sets,
    fetch_rank_response,
    fetch_shared_targets,
    fetch_target_sets,
    fetch_topn_percent_responsive,
    has_top_n,
    regulator_intersection,
    resolve_promoter_variant,
    sort_regulators_by_symbol,
    table_exists,
    weighted_agreement,
)
from tfbpshiny.utils.figure import (
    BINDING_COLORS,
    METHOD_COLORS,
    PERTURBATION_COLORS,
    PROMOTER_SET_COLORS,
    figure_html,
    matplotlib_svg_html,
)
from tfbpshiny.utils.perf import perf, reset_render_counts
from tfbpshiny.utils.vdb_init import get_regulator_display_name

#: Display labels for the promoter-set/method box axes, local to this module (mirrors
#: `modules/comparison/server/workspace.py`'s own `_PROMOTER_SET_ALIAS`-style
#: dicts, kept separate per this app's module-isolation convention).
_PROMOTER_SET_LABELS: dict[str, str] = {
    "kang": "Kang",
    "mindel": "Mindel",
    "500bp": "500 bp",
    "intergenic": "Intergenic",
}
_METHOD_LABELS: dict[str, str] = {
    "promoter_enrichment": "Promoter Enrichment",
    "peak_calling": "Peak Calling",
}

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
    _reg_symbols: dict[str, str] = {}
    for _, row in _reg_df.iterrows():
        tag = str(row["regulator_locus_tag"])
        sym = str(row.get("regulator_symbol", ""))
        if sym and sym not in ("nan", tag):
            _reg_labels[tag] = f"{sym} ({tag})"
            _reg_symbols[tag] = sym
        else:
            _reg_labels[tag] = tag

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
    _target_sets_available = table_exists(conn, "topn_target_sets")
    for name, ok in (
        ("authors'-binding-threshold rows", _authors_bound_available),
        ("topn_agreement", _agreement_available),
        ("topn_target_sets", _target_sets_available),
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
    def _fig7_tf_sets() -> dict[str, list[str]]:
        """
        Regulators in (Calling Cards, Rossi, ChEC-seq) ∩ each perturbation dataset, for
        figures 7 and 9's top-N response-rate grids.

        Deliberately not ``_tf_sets()``: that one intersects over ``BINDING_ORDER``,
        which includes Harbison -- Harbison has no promoter-set variants at all, so
        including it would only shrink this population for no reason.

        :trigger: none -- depends only on the database.

        """
        return {
            p: regulator_intersection(conn, list(DTO_BINDING_ORDER) + [p])
            for p in PR_ORDER
        }

    @reactive.calc
    def _fig9_tf_sets() -> dict[str, list[str]]:
        """
        Regulators in (Rossi, ChEC-seq) ∩ each perturbation dataset, for figure 9's top
        grid -- the two binding primaries with a peak-calling arm.

        :trigger: none -- depends only on the database.

        """
        return {
            p: regulator_intersection(conn, list(METHOD_COMPARISON_BINDING) + [p])
            for p in PR_ORDER
        }

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

    def _read_dto_venn_layout() -> str:
        try:
            return str(input.dto_venn_layout())
        except Exception:
            return DTO_VENN_LAYOUT_DEFAULT

    # ------------------------------------------------------------------
    # Sidebar
    # ------------------------------------------------------------------

    #: Default featured TF (GZF3), used when present in the intersection. Picked as a
    #: representative example rather than for any statistical reason; falls back to
    #: the first TF alphabetically if a future intersection ever excludes it.
    _DEFAULT_FEATURED_TF = "YJL110C"

    @render.ui
    def tf_selector() -> ui.Tag:
        """
        Selector for the TF featured in figure 1.

        :trigger: ``_featured_tfs``.

        """
        tfs = sort_regulators_by_symbol(_featured_tfs(), _reg_symbols)
        if not tfs:
            return ui.span()
        default = _DEFAULT_FEATURED_TF if _DEFAULT_FEATURED_TF in tfs else tfs[0]
        return ui.div(
            ui.tags.label("Featured TF", class_="form-label mt-3 mb-1"),
            ui.input_select(
                "featured_tf",
                label=None,
                choices={t: _reg_labels.get(t, t) for t in tfs},
                selected=default,
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
                    title=f"{_labels.get(p, p)}  (n={len(tfs)} TFs)",
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

        :trigger: ``input.dto_venn_layout`` -- toggles between the default
            (exact-when-possible, else equal circles) and cost-based (approximate,
            more often proportional) layouts.

        """
        if not _dto_available:
            return _dto_missing()
        layout = _read_dto_venn_layout()
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
                    layout=layout,
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
    # A default naming a dataset the registry does not have is dropped by the
    # membership filter in _agreement_selection, which would quietly shrink figure 6
    # rather than fail. Renames make that a live risk, so say so.
    for _ctype, _defaults in _agreement_defaults.items():
        _missing = [d for d in _defaults if d not in _agreement_choices.get(_ctype, {})]
        if _missing and _agreement_available:
            logger.warning(
                "figures: figure 6's default %s datasets %s are not in"
                " dataset_registry and will be dropped from the default view;"
                " check for a renamed db_name",
                _ctype,
                _missing,
            )

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
            every pair among the selected datasets is drawn -- and ``dataset_filters``.

        """
        if not _agreement_available:
            return {}
        filters = dataset_filters()
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
                out[ctype] = fetch_agreement(conn, ctype, selected, filters)
            return out

    def _read_half_life(ctype: str) -> int:
        """
        The selected exponential weighting half-life for one panel, in units of N.

        Binding and perturbation have separate sliders -- they are ranked on
        different quantities (rank column vs. absolute effect) and need not decay at
        the same rate. Falls back to the default before the slider has registered.

        :param ctype: ``'binding'`` or ``'perturbation'``.

        """
        try:
            return int(getattr(input, f"agreement_half_life_{ctype}")())
        except Exception:
            return AGREEMENT_HALF_LIFE_DEFAULT

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

    _AGREEMENT_HEADINGS: dict[str, str] = {
        "binding": "Binding vs. binding",
        "perturbation": "Perturbation vs. perturbation",
    }

    def _fig_agreement_block(ctype: str) -> ui.Tag:
        """
        One figure-6 block (curve + weighted box) for one comparison type.

        Factored out of a single combined render so the binding and perturbation
        blocks can sit in separate ``ui.output_ui`` slots -- each with its own
        weighting-half-life slider immediately above it, rather than both sliders
        stacked above both plots.

        :param ctype: ``'binding'`` or ``'perturbation'``.

        """
        heading = _AGREEMENT_HEADINGS[ctype]
        if not _agreement_available:
            return _needs_rebuild("The dataset-agreement table")
        try:
            tf = str(input.featured_tf())
        except Exception:
            tf = ""
        half_life = _read_half_life(ctype)
        df = _agreement().get(ctype, pd.DataFrame())
        if df.empty:
            note = _agreement_empty_note(ctype, heading)
            return note if note is not None else ui.div()
        curve_src = df[df["regulator_locus_tag"] == tf] if tf else df
        panels = []
        if not curve_src.empty:
            panels.append(
                ui.div(
                    figure_html(
                        agreement_curve_figure(
                            curve_src,
                            title=(f"{heading} — {_reg_labels.get(tf, tf)}"),
                            half_life=half_life,
                        ),
                        filename=f"fig6_agreement_curve_{ctype}_{tf}",
                    ),
                    style="flex: 1 1 0; min-width: 520px;",
                )
            )
        weighted = weighted_agreement(df, half_life=half_life)
        if not weighted.empty:
            panels.append(
                ui.div(
                    figure_html(
                        agreement_box_figure(
                            weighted,
                            title=f"{heading} — all TFs",
                            half_life=half_life,
                        ),
                        filename=f"fig6_agreement_weighted_{ctype}_hl{half_life}",
                    ),
                    style="flex: 1 1 0; min-width: 520px;",
                )
            )
        if not panels:
            return ui.div({"class": "empty-state"}, ui.p("No agreement results."))
        return ui.div(
            {
                "style": (
                    "display: flex; gap: 1.5rem;"
                    " align-items: flex-start; flex-wrap: wrap;"
                )
            },
            *panels,
        )

    @render.ui
    def fig_agreement_binding() -> ui.Tag:
        """
        Overlap enrichment vs N, binding vs. binding.

        :trigger: ``_agreement`` / ``input.featured_tf`` /
            ``input.agreement_half_life_binding``.

        """
        with perf(session.id, "figures.workspace", "fig_agreement_binding"):
            return _fig_agreement_block("binding")

    @render.ui
    def fig_agreement_perturbation() -> ui.Tag:
        """
        Overlap enrichment vs N, perturbation vs. perturbation.

        :trigger: ``_agreement`` / ``input.featured_tf`` /
            ``input.agreement_half_life_perturbation``.

        """
        with perf(session.id, "figures.workspace", "fig_agreement_perturbation"):
            return _fig_agreement_block("perturbation")

    # ------------------------------------------------------------------
    # Figure 10 -- targets shared between two datasets
    # ------------------------------------------------------------------

    def _shared_datasets(ctype: str) -> list[str]:
        """
        Datasets figure 10 compares, matching figure 6's defaults so pair labels and
        colours agree between the two.

        Binding is the three 500 bp promoter-enrichment variants; perturbation is the
        three headline datasets.

        :param ctype: ``'binding'`` or ``'perturbation'``.
        :returns: db_names present in the agreement table's registry.

        """
        available = _agreement_choices.get(ctype, {})
        return [d for d in _agreement_defaults[ctype] if d in available]

    def _fig_shared_targets_block(ctype: str) -> ui.Tag:
        """
        One figure-10 row: the featured TF's Venn on the left, the distribution of
        shared targets across TFs on the right -- the same order as figure 6.

        Both read ``topn_target_sets`` at the sidebar's Top N, under the app's
        dataset filters, so they describe the same samples.

        :param ctype: ``'binding'`` or ``'perturbation'``.

        """
        heading = _AGREEMENT_HEADINGS[ctype]
        if not _target_sets_available:
            return _needs_rebuild("The top-N target sets")
        datasets = _shared_datasets(ctype)
        top_n = _read_top_n()
        filters = dataset_filters()
        try:
            tf = str(input.featured_tf())
        except Exception:
            tf = ""
        palette = BINDING_COLORS if ctype == "binding" else PERTURBATION_COLORS
        panels = []
        sets = fetch_target_sets(conn, datasets, tf, top_n, filters) if tf else {}
        if any(sets.values()):
            mpl_fig = dto_venn_figure(
                sets,
                _labels,
                datasets,
                title=f"{heading} — {_reg_labels.get(tf, tf)}, top {top_n}",
                colors=palette,
            )
            panels.append(
                ui.div(
                    matplotlib_svg_html(
                        mpl_fig,
                        alt=f"Top-{top_n} target Venn, {ctype}, {tf}",
                        filename=f"fig10_venn_{ctype}_{tf}_top{top_n}",
                    ),
                    style="flex: 1 1 0; min-width: 380px;",
                )
            )
        df = fetch_shared_targets(conn, ctype, datasets, top_n, filters)
        if not df.empty:
            n_tfs = df["regulator_locus_tag"].nunique()
            fig = shared_targets_box_figure(
                df, top_n=top_n, title=f"{heading} — all TFs (n={n_tfs})"
            )
            panels.append(
                ui.div(
                    figure_html(
                        fig, filename=f"fig10_shared_targets_{ctype}_top{top_n}"
                    ),
                    style="flex: 1 1 0; min-width: 520px;",
                )
            )
        if not panels:
            return ui.div(
                {"class": "empty-state"},
                ui.p(f"{heading}: no target sets for these datasets."),
            )
        return ui.div(
            {
                "style": (
                    "display: flex; gap: 1.5rem;"
                    " align-items: flex-start; flex-wrap: wrap;"
                )
            },
            *panels,
        )

    @render.ui
    def fig_shared_targets_binding() -> ui.Tag:
        """
        Featured-TF Venn and shared-target boxes, binding vs. binding.

        :trigger: ``input.featured_tf`` / ``input.box_top_n`` / ``dataset_filters``.

        """
        with perf(session.id, "figures.workspace", "fig_shared_targets_binding"):
            return _fig_shared_targets_block("binding")

    @render.ui
    def fig_shared_targets_perturbation() -> ui.Tag:
        """
        Featured-TF Venn and shared-target boxes, perturbation vs. perturbation.

        :trigger: ``input.featured_tf`` / ``input.box_top_n`` / ``dataset_filters``.

        """
        with perf(session.id, "figures.workspace", "fig_shared_targets_perturbation"):
            return _fig_shared_targets_block("perturbation")

    # ------------------------------------------------------------------
    # Figures 7, 8, 9 -- promoter-definition and method comparisons as box plots
    # ------------------------------------------------------------------
    #
    # These port what the Comparison module's "Compare Promoter Definitions" and
    # "Compare Analysis Methods" tabs already show as a table of medians, but as the
    # actual distribution across TFs, faceted by binding dataset (rows) AND
    # perturbation dataset (columns) at once -- the first two-axis grid in this
    # module (every other figure facets on only one axis, folding the other into a
    # trace loop within each panel). See `binding_perturbation_box_grid`.

    def _resolve_variant_cells(
        binding_primaries: tuple[str, ...], combos: list[tuple[str, str, str]]
    ) -> dict[str, tuple[str, str]]:
        """
        ``variant db_name -> (binding_primary, box_key)``, for every combination that
        resolves to a real dataset.

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

    def _topn_box_panels(
        variant_cell: dict[str, tuple[str, str]],
        tf_sets: dict[str, list[str]],
    ) -> dict[tuple[str, str], pd.DataFrame]:
        """
        Top-N percent responsive per regulator, reshaped to ``(binding_primary, pr_db)
        -> [box_key, value]`` for :func:`binding_perturbation_box_grid`.

        One query per perturbation dataset covers every variant at once --
        ``fetch_topn_percent_responsive`` already accepts a list of binding_dbs.

        """
        filters = dataset_filters()
        preset = _read_scoring()
        top_n = _read_top_n()
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
    ) -> dict[tuple[str, str], pd.DataFrame]:
        """
        Figure 9 top grid's per-box data: like :func:`_topn_box_panels`, but keeps a
        regulator only where promoter enrichment AND peak calling both have a row (see
        :func:`~tfbpshiny.materialize.comparison.method_promoter_model.

        pair_methods_on_regulators`), so the two boxes describe the same TFs. A TF with
        no usable peak-calling list is dropped from both boxes, not scored as zero.
        ``variant_cell``'s box_key is the method id here (:data:`METHOD_LEVELS`), which
        doubles as the pairing's method column.

        """
        filters = dataset_filters()
        preset = _read_scoring()
        top_n = _read_top_n()
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

    def _dto_bar_panels(
        variant_cell: dict[str, tuple[str, str]],
    ) -> dict[tuple[str, str], pd.DataFrame]:
        """
        DTO significance fraction per regulator population, reshaped the same way as
        :func:`_topn_box_panels`.

        One ``fetch_dto_significance`` call per (variant,
        perturbation dataset) pair -- reusing figure 4's own query function, called
        per-variant instead of over the fixed :data:`DTO_BINDING_ORDER` list.

        """
        if not _dto_available:
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

    def _fig9_dto_bar_panels(
        variant_cell: dict[str, tuple[str, str]],
    ) -> dict[tuple[str, str], pd.DataFrame]:
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
        if not _dto_available:
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
    def _fig7_panels() -> dict[tuple[str, str], pd.DataFrame]:
        """
        Figure 7's data: top-N percent responsive, one box per promoter set.

        :trigger: ``dataset_filters`` / ``input.scoring`` / ``input.box_top_n``.

        """
        with perf(session.id, "figures.workspace", "_fig7_panels", kind="data"):
            combos = [(ps, "promoter_enrichment", ps) for ps in PROMOTER_SET_LEVELS]
            variant_cell = _resolve_variant_cells(DTO_BINDING_ORDER, combos)
            return _topn_box_panels(variant_cell, _fig7_tf_sets())

    @reactive.calc
    def _fig8_panels() -> dict[tuple[str, str], pd.DataFrame]:
        """
        Figure 8's data: % of shared TFs that are DTO-significant, one bar per promoter
        set.

        :trigger: none beyond the database.

        """
        with perf(session.id, "figures.workspace", "_fig8_panels", kind="data"):
            combos = [(ps, "promoter_enrichment", ps) for ps in PROMOTER_SET_LEVELS]
            variant_cell = _resolve_variant_cells(DTO_BINDING_ORDER, combos)
            return _dto_bar_panels(variant_cell)

    @reactive.calc
    def _fig9_top_panels() -> dict[tuple[str, str], pd.DataFrame]:
        """
        Figure 9's top grid: top-N percent responsive, one box per method, at 500bp.

        :trigger: ``dataset_filters`` / ``input.scoring`` / ``input.box_top_n``.

        """
        with perf(session.id, "figures.workspace", "_fig9_top_panels", kind="data"):
            combos = [("500bp", m, m) for m in METHOD_LEVELS]
            variant_cell = _resolve_variant_cells(METHOD_COMPARISON_BINDING, combos)
            return _fig9_topn_box_panels(variant_cell, _fig9_tf_sets())

    @reactive.calc
    def _fig9_bottom_panels() -> dict[tuple[str, str], pd.DataFrame]:
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
                return ui.div(
                    {"class": "empty-state"}, ui.p("No data for these datasets.")
                )
            fig = binding_perturbation_box_grid(
                panels,
                list(DTO_BINDING_ORDER),
                list(PR_ORDER),
                list(PROMOTER_SET_LEVELS),
                _labels,
                _labels,
                _PROMOTER_SET_LABELS,
                PROMOTER_SET_COLORS,
                y_title=f"% responsive in top {_read_top_n()}",
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
        if not _dto_available:
            return _dto_missing()
        with perf(session.id, "figures.workspace", "fig_dto_significance_grid"):
            panels = _fig8_panels()
            if not panels:
                return ui.div({"class": "empty-state"}, ui.p("No DTO results."))
            fig = binding_perturbation_bar_grid(
                panels,
                list(DTO_BINDING_ORDER),
                list(PR_ORDER),
                list(PROMOTER_SET_LEVELS),
                _labels,
                _labels,
                _PROMOTER_SET_LABELS,
                PROMOTER_SET_COLORS,
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
                    _labels,
                    _labels,
                    _METHOD_LABELS,
                    METHOD_COLORS,
                    y_title=f"% responsive in top {_read_top_n()}",
                    y_range=FIG7_RESPONSE_Y,
                )
                blocks.append(figure_html(top_fig, filename="fig9_topn_boxes"))
            else:
                blocks.append(
                    ui.div(
                        {"class": "empty-state"}, ui.p("No data for these datasets.")
                    )
                )

            if not _dto_available:
                blocks.append(_dto_missing())
            else:
                bottom_panels = _fig9_bottom_panels()
                if bottom_panels:
                    bottom_fig = binding_perturbation_bar_grid(
                        bottom_panels,
                        list(METHOD_COMPARISON_BINDING),
                        list(PR_ORDER),
                        list(METHOD_LEVELS),
                        _labels,
                        _labels,
                        _METHOD_LABELS,
                        METHOD_COLORS,
                        y_title="% of shared TFs (DTO p < 0.01)",
                    )
                    blocks.append(figure_html(bottom_fig, filename="fig9_dto_bars"))
                else:
                    blocks.append(
                        ui.div({"class": "empty-state"}, ui.p("No DTO results."))
                    )
            return ui.div(*blocks)


__all__ = ["figures_workspace_server"]
