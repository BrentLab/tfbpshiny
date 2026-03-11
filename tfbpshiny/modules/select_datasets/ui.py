"""UI functions for the Select Datasets page."""

from __future__ import annotations

from typing import Any

import pandas as pd
from shiny import module, ui

from tfbpshiny.modules.module_template import workspace_shell


def _filter_control(
    field: str,
    col: pd.Series,
    saved_spec: dict[str, Any] | None,
) -> ui.Tag | None:
    """
    Build a single filter-option card for ``field``.

    Returns ``None`` if the field type is not filterable or has no usable data.

    """
    dtype = col.dtype

    if dtype == "bool":
        saved_val = bool(saved_spec["value"]) if saved_spec else False
        return ui.div(
            {"class": "filter-option-card"},
            ui.div(
                {"class": "filter-option-header"},
                ui.span({"class": "filter-option-title"}, field),
            ),
            ui.input_switch(f"filter_{field}", label=field, value=saved_val),
        )

    if dtype.name in ("object", "category"):
        choices = sorted(str(v) for v in col.dropna().unique())
        selected = saved_spec["value"] if saved_spec else []
        return ui.div(
            {"class": "filter-option-card"},
            ui.div(
                {"class": "filter-option-header"},
                ui.span({"class": "filter-option-title"}, field),
            ),
            ui.input_selectize(
                f"filter_{field}",
                label=None,
                choices=choices,
                selected=selected,
                multiple=True,
                options={"plugins": ["remove_button"]},
            ),
        )

    if dtype.name in ("float64", "int64", "float32", "int32"):
        non_null = col.dropna()
        if non_null.empty:
            return None
        data_min = float(non_null.min())
        data_max = float(non_null.max())
        if data_min == data_max:
            data_max = data_min + 1.0
        # TODO: fix typing issue and remove type: ignore
        saved_val = saved_spec["value"] if saved_spec else [data_min, data_max]  # type: ignore # noqa: E501
        return ui.div(
            {"class": "filter-option-card"},
            ui.div(
                {"class": "filter-option-header"},
                ui.span({"class": "filter-option-title"}, field),
            ),
            ui.input_slider(
                f"filter_{field}",
                label=None,
                min=data_min,
                max=data_max,
                value=saved_val,
            ),
        )

    return None


def _section_heading(label: str) -> ui.Tag:
    return ui.div(
        {
            "style": "font-weight:bold; border-bottom: 1px solid #e0e0e0;"
            " padding-bottom:4px; margin-bottom:6px;"
        },
        label,
    )


def dataset_filter_modal_ui(
    db_name: str,
    df: pd.DataFrame,
    saved_filters: dict[str, Any] | None = None,
    common_fields: set[str] | None = None,
) -> ui.Tag:
    """
    Build the filter modal for a given dataset from live metadata.

    Fields that appear in every dataset's ``_meta`` view (``common_fields``) are
    shown in their own labelled section at the top; dataset-specific fields follow.
    Setting a common field applies that filter to all datasets.

    :param db_name: Dataset name used as the modal title.
    :param df: Metadata DataFrame from ``vdb.query(metadata_query(db_name, ...))``.
    :param saved_filters: Previously applied filters for this dataset, used to
        pre-populate controls.
    :param common_fields: Field names shared across all datasets. If ``None``,
        all fields are treated as dataset-specific.

    """
    saved = saved_filters or {}
    cf = (common_fields or set()) - {"sample_id"}

    common_cards: list[ui.Tag] = []
    specific_cards: list[ui.Tag] = []

    for field in df.columns:
        if field == "sample_id":
            continue
        card = _filter_control(field, df[field], saved.get(field))
        if card is None:
            continue
        if field in cf:
            common_cards.append(card)
        else:
            specific_cards.append(card)

    sections: list[ui.Tag] = []

    if common_cards:
        sections.append(_section_heading("Common Fields"))
        sections.extend(common_cards)

    if specific_cards:
        sections.append(_section_heading("Dataset Fields"))
        sections.extend(specific_cards)

    if not sections:
        sections.append(ui.p("No filterable fields available for this dataset."))

    return ui.modal(
        ui.div({"class": "modal-section"}, *sections),
        title=db_name,
        size="l",
        easy_close=True,
        footer=ui.div(
            ui.input_action_button(
                "modal_reset_filters",
                "Reset",
                class_="btn btn-sm btn-outline-secondary",
            ),
            ui.input_action_button(
                "modal_apply_filters",
                "Apply Filters",
                class_="btn btn-sm btn-primary",
            ),
        ),
    )


@module.ui
def selection_sidebar_ui() -> ui.Tag:
    """Render the Active Set sidebar shell."""
    return ui.output_ui("sidebar_panel")


@module.ui
def selection_matrix_ui() -> ui.Tag:
    """Render the intersection matrix workspace."""
    return workspace_shell(
        "selection-workspace",
        header=ui.h1("Intersection Summary"),
        body=ui.output_ui("matrix_content"),
    )


__all__ = ["dataset_filter_modal_ui", "selection_sidebar_ui", "selection_matrix_ui"]
