"""Tab 4, Method x Promoter Model: the precomputed pooled-OLS results."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd
from shiny import reactive, render, ui

from tfbpshiny.components import empty_state
from tfbpshiny.modules.comparison.queries import (
    fetch_method_promoter_model,
    fetch_method_promoter_target_universe,
)
from tfbpshiny.modules.comparison.server.context import (
    ComparisonContext,
    read_preset_name,
    read_top_n,
)
from tfbpshiny.modules.comparison.server.shared import Shared
from tfbpshiny.utils.perf import perf


def mm_term_label(term: str) -> str:
    """
    Shorten a patsy term name for display, e.g. drop the ``C(..., Treatment(...))``
    wrapper down to just the factor and level.

    ``"C(method, Treatment('promoter_enrichment'))[T.peak_calling]"`` becomes
    ``"method[peak_calling]"``; interaction terms keep the ``:`` separator between
    shortened pieces. Falls back to the raw term unchanged if it doesn't match the
    expected patsy shape, so an unrecognized term is still shown, just unprettified.

    :param term: Raw patsy/statsmodels coefficient or test-block name.
    :returns: Shortened label.

    """

    def _shorten_piece(piece: str) -> str:
        m = re.match(r"C\((\w+),\s*Treatment\([^)]*\)\)(?:\[T\.(.+)\])?", piece)
        if not m:
            return piece
        factor, level = m.group(1), m.group(2)
        return f"{factor}[{level}]" if level else factor

    if term == "Intercept":
        return term
    return ":".join(_shorten_piece(p) for p in term.split(":"))


def summary_table(
    df: pd.DataFrame,
    columns: list[tuple[str, str, str]],
    *,
    label_col: str | None = None,
) -> ui.Tag:
    """
    Render a DataFrame as an R-``summary(lm())``-style HTML table.

    :param df: Rows to render, in the order given.
    :param columns: ``(df_column, header_label, format_spec)`` tuples. ``format_spec``
        is a Python format spec applied via ``f"{value:{format_spec}}"``, or ``""``
        for plain string conversion.
    :param label_col: If given, this column's values are shortened via
        :func:`mm_term_label` before display (used for term/test-name columns).
    :returns: A ``ui.tags.table``, or an empty-state div if `df` is empty.

    """
    if df.empty:
        return empty_state(ui.p("No rows."))
    header_cells = [
        ui.tags.th(label, style="padding: 4px 10px; text-align: right;")
        for _, label, _ in columns
    ]
    data_rows = []
    for _, row in df.iterrows():
        cells = []
        for col, _, fmt in columns:
            val = row[col]
            if col == label_col:
                text = mm_term_label(str(val))
            elif pd.isna(val):
                text = "—"
            elif fmt:
                text = f"{val:{fmt}}"
            else:
                text = str(val)
            cells.append(
                ui.tags.td(text, style="padding: 4px 10px; text-align: right;")
            )
        data_rows.append(ui.tags.tr(*cells))
    return ui.tags.table(
        {
            "style": "border-collapse: collapse; font-size: 0.85rem; font-family:"
            " ui-monospace, monospace;"
        },
        ui.tags.thead(
            {"style": "background-color: #f5f5f5;"}, ui.tags.tr(*header_cells)
        ),
        ui.tags.tbody(*data_rows),
    )


def register_method_model(
    input: Any, session: Any, ctx: ComparisonContext, shared: Shared
) -> None:
    """
    Register the Method x Promoter Model tab's reactives and output.

    :param input: Shiny input object of the comparison module.
    :param session: Module session.
    :param ctx: Per-session context.
    :param shared: Shared helpers (unused here; kept for a uniform signature).

    """
    conn = ctx.conn

    @reactive.calc
    def _mm_data() -> dict[str, tuple[pd.DataFrame, pd.DataFrame]]:
        """
        Precomputed method x promoter-set model results, one entry per active
        perturbation dataset.

        Reads only -- the model itself is fit once, offline, by
        ``tfbpshiny materialize`` (see ``materialize/comparison/
        method_promoter_model.py``). No fitting happens in the app.

        :trigger: ``input.top_n`` / ``input.responsiveness_preset`` — shared sidebar
            controls.
        :trigger: ``active_perturbation_datasets`` — committed dataset selection.

        """
        n = read_top_n(input)
        preset_name = read_preset_name(input)
        out: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
        with perf(session.id, "comparison.workspace", "_mm_data", kind="data"):
            for p_db in ctx.active_perturbation_datasets():
                try:
                    out[p_db] = fetch_method_promoter_model(conn, p_db, n, preset_name)
                except Exception:
                    ctx.logger.exception("mm_data fetch failed for %s", p_db)
        return out

    @reactive.calc
    def _mm_target_universe() -> pd.DataFrame:
        """
        Per-assay size of the cross-promoter-set target intersection.

        Materialized once, offline (see ``materialize/comparison/
        method_promoter_model.py::promoter_set_target_universe``); does not depend on
        the selected perturbation dataset, top-N, or preset, so this is read once and
        reused across every panel :func:`mm_model_tables` draws.

        :trigger: None -- this table has exactly one row per assay, always.

        """
        with perf(
            session.id, "comparison.workspace", "_mm_target_universe", kind="data"
        ):
            try:
                return fetch_method_promoter_target_universe(conn)
            except Exception:
                ctx.logger.exception("mm_target_universe fetch failed")
                return pd.DataFrame(
                    columns=["assay_primary", "display_name", "n_targets"]
                )

    @render.ui
    def mm_model_tables() -> ui.Tag:
        """
        Method x promoter-set model: target-universe sizes, fit summary and
        coefficients.

        One panel per active perturbation dataset, matching every other tab in this
        module. The model itself is precomputed (see ``_mm_data``); this only formats
        it. A fixed-effects OLS (regulator + assay as covariates), not a mixed model --
        cluster-robust standard errors by regulator, not a variance-component
        decomposition. Baselines are ``peak_calling`` and ``intergenic``, so every
        displayed method/promoter-set coefficient reads as a contrast against those.

        :trigger: ``_mm_data``, ``_mm_target_universe``.

        """
        with perf(session.id, "comparison.workspace", "mm_model_tables"):
            data = _mm_data()
            p_dbs = ctx.active_perturbation_datasets()
            if not p_dbs:
                return empty_state(
                    ui.p("No perturbation datasets selected."),
                )
            universe_df = _mm_target_universe()
            panels: list[Any] = []
            if not universe_df.empty:
                n_targets_values = universe_df["n_targets"].unique()
                if len(n_targets_values) == 1:
                    # The intersection is a property of genome annotation (which
                    # genes have a defined promoter window in all four promoter
                    # sets), not of the assay, so every assay lands on the same
                    # number -- confirmed live against both Rossi and ChEC-seq.
                    caption = (
                        "The regression is performed over the"
                        f" {int(n_targets_values[0])} targets in the intersect"
                        " between all four promoter set definitions."
                    )
                else:
                    items = ", ".join(
                        f"{row['display_name']}: {int(row['n_targets'])} targets"
                        for _, row in universe_df.iterrows()
                    )
                    caption = (
                        "Every cell below is ranked over the intersection of"
                        " targets present in all four promoter sets' promoter-"
                        f" enrichment data, per assay -- {items}."
                    )
                panels.append(ui.p(ui.tags.em(caption), style="margin-bottom: 1rem;"))
            for p_db in p_dbs:
                bundle = data.get(p_db)
                p_label = ctx.base_label.get(p_db, p_db)
                if bundle is None or bundle[1].empty:
                    panels.append(
                        empty_state(
                            ui.p(
                                f"{p_label}: no model results for this cutoff/preset."
                                " Rebuild with ",
                                ui.tags.code("tfbpshiny materialize"),
                                " to compute the method x promoter-set model.",
                            ),
                        )
                    )
                    continue

                coefs, fit_summary = bundle
                summ = fit_summary.iloc[0]
                if not summ["converged"]:
                    panels.append(
                        empty_state(
                            ui.p(
                                ui.strong(f"{p_label}: model did not converge."),
                                f" {summ['note'] or ''}",
                            ),
                        )
                    )
                    continue

                summary_text = (
                    f"{int(summ['n_obs'])} observations,"
                    f" {int(summ['n_regulators'])} regulators, R² ="
                    f" {summ['r_squared']:.2f}."
                )
                panels.append(
                    ui.div(
                        {
                            "style": (
                                "border: 1px solid #ddd; border-radius: 4px;"
                                " padding: 12px; margin-bottom: 1.5rem;"
                            )
                        },
                        ui.h4(p_label, style="margin-top: 0;"),
                        ui.p(ui.tags.em(summary_text)),
                        summary_table(
                            coefs,
                            [
                                ("term", "term", ""),
                                ("estimate", "Estimate (pp)", ".3f"),
                                ("std_error", "Std. Error (pp)", ".3f"),
                                ("t_value", "t value", ".2f"),
                                ("p_value", "Pr(>|t|)", ".3g"),
                            ],
                            label_col="term",
                        ),
                    )
                )
            return ui.div(*panels)


__all__ = ["mm_term_label", "register_method_model", "summary_table"]
