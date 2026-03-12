"""Sidebar server for the Binding analysis page."""

from __future__ import annotations

from logging import Logger
from typing import Any

from shiny import module, reactive, render, ui
from tfbpapi import VirtualDB


def _get_numeric_columns(vdb: VirtualDB, db_name: str) -> list[str]:
    """Return numeric data columns for a binding dataset (excludes ID columns)."""
    _id_cols = {"regulator_locus_tag", "target_locus_tag", "sample_id", "id"}
    try:
        desc = vdb.describe(db_name)
        numeric_types = {
            "FLOAT",
            "DOUBLE",
            "INTEGER",
            "BIGINT",
            "HUGEINT",
            "FLOAT4",
            "FLOAT8",
            "INT",
            "INT4",
            "INT8",
        }
        cols = [
            row["column_name"]
            for _, row in desc.iterrows()
            if row["column_name"] not in _id_cols
            and any(t in str(row["column_type"]).upper() for t in numeric_types)
        ]
        return sorted(cols)
    except Exception:
        return []


@module.server
def binding_sidebar_server(
    input: Any,
    output: Any,
    session: Any,
    active_binding_datasets: reactive.calc,
    dataset_filters: reactive.Value[dict[str, Any]],
    vdb: VirtualDB,
    logger: Logger,
) -> tuple[
    reactive.calc,  # corr_type: "pearson" | "spearman"
    reactive.calc,  # column: str | None — shared column name across datasets
]:
    """
    Render binding analysis sidebar controls; return reactive selections.

    :return: Tuple of (corr_type, column).

    """

    @reactive.calc
    def _common_columns() -> list[str]:
        """Columns present in ALL active binding datasets (intersection)."""
        active = active_binding_datasets()
        if not active:
            return []
        col_sets = [set(_get_numeric_columns(vdb, db)) for db in active]
        return sorted(set.intersection(*col_sets)) if col_sets else []

    @reactive.calc
    def corr_type() -> str:
        try:
            return str(input.corr_type())
        except Exception:
            return "pearson"

    @reactive.calc
    def column() -> str | None:
        cols = _common_columns()
        if not cols:
            return None
        try:
            val = str(input.column())
            if val in cols:
                return val
        except Exception:
            pass
        # prefer pvalue as default if available
        if "pvalue" in cols:
            return "pvalue"
        return cols[0]

    @render.ui
    def sidebar_controls() -> ui.Tag:
        active = active_binding_datasets()

        if not active:
            return ui.div(
                {"class": "empty-state compact"},
                ui.p("Select binding datasets from the Select Datasets page."),
            )

        cols = _common_columns()

        return ui.div(
            ui.div(
                {"class": "sidebar-section"},
                ui.div({"class": "sidebar-section-title"}, "Column"),
                (
                    ui.input_select(
                        "column",
                        label=None,
                        choices={c: c for c in cols},
                        selected=column(),
                    )
                    if cols
                    else ui.p(
                        {"class": "text-muted"},
                        "No column shared across all active datasets.",
                    )
                ),
            ),
            ui.div(
                {"class": "sidebar-section"},
                ui.div({"class": "sidebar-section-title"}, "Correlation"),
                ui.input_radio_buttons(
                    "corr_type",
                    label=None,
                    choices={"pearson": "Pearson", "spearman": "Spearman"},
                    selected=corr_type(),
                    inline=True,
                ),
            ),
        )

    return corr_type, column


__all__ = ["binding_sidebar_server"]
