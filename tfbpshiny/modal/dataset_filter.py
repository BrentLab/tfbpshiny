"""Dataset filter/config modal UI."""

from __future__ import annotations

from typing import Any

from shiny import ui

# #MOCK — static filter options shown in dataset config modal
_MOCK_FILTER_OPTIONS: list[dict[str, Any]] = [
    {
        "field": "carbon_source",
        "kind": "categorical",
        "values": ["glucose", "galactose", "raffinose"],
    },
    {
        "field": "temperature_celsius",
        "kind": "numeric",
        "min_value": 25.0,
        "max_value": 37.0,
    },
]


def _dataset_type_badge(dataset_type: str) -> tuple[str, str]:
    if dataset_type == "Binding":
        return ("BD", "badge-bd")
    if dataset_type == "Perturbation":
        return ("PR", "badge-pr")
    return ("EX", "badge-ex")


def render_dataset_config_modal(dataset: dict[str, Any]) -> ui.Tag:
    """Render DatasetConfigModal-like UI as an overlay panel."""
    badge_text, badge_class = _dataset_type_badge(
        str(dataset.get("type", "Expression"))
    )
    sample_count = int(dataset.get("sample_count") or 0)
    sample_count_known = bool(dataset.get("sample_count_known"))
    column_count = int(dataset.get("column_count") or 0)

    option_sections: list[ui.Tag] = []
    for option in _MOCK_FILTER_OPTIONS:
        field = str(option["field"])
        if option["kind"] == "numeric":
            option_sections.append(
                ui.div(
                    {"class": "filter-option-card"},
                    ui.div(
                        {"class": "filter-option-header"},
                        ui.span({"class": "filter-option-title"}, field),
                        ui.span({"class": "badge badge-count"}, "no range"),
                    ),
                    ui.div(
                        {"class": "filter-option-help"},
                        f"Min: {option.get('min_value', 'N/A')} "
                        f"· Max: {option.get('max_value', 'N/A')}",
                    ),
                    ui.div(
                        {"class": "numeric-filter-grid"},
                        ui.input_text(f"mock_num_{field}_min", "Min", value=""),
                        ui.input_text(f"mock_num_{field}_max", "Max", value=""),
                    ),
                )
            )
        else:
            choices = [str(v) for v in option.get("values", [])]
            option_sections.append(
                ui.div(
                    {"class": "filter-option-card"},
                    ui.div(
                        {"class": "filter-option-header"},
                        ui.span({"class": "filter-option-title"}, field),
                        ui.span({"class": "badge badge-count"}, "0 selected"),
                    ),
                    ui.input_selectize(
                        f"mock_cat_{field}",
                        label=None,
                        choices=choices,
                        selected=[],
                        multiple=True,
                        options={"plugins": ["remove_button"]},
                    ),
                )
            )

    return ui.div(
        {"class": "modal-overlay"},
        ui.div(
            {"class": "modal-card modal-large"},
            ui.div(
                {"class": "modal-panel-header"},
                ui.div(
                    ui.div(
                        {"class": "modal-title-row"},
                        ui.span({"class": f"badge {badge_class}"}, badge_text),
                        ui.h3(str(dataset.get("name", "Dataset"))),
                        ui.span({"class": "badge"}, "0 filters"),
                    ),
                    ui.div(
                        {"class": "modal-subtitle-row"},
                        (
                            f"{sample_count:,} rows"
                            if sample_count_known
                            else "rows pending"
                        ),
                        " · ",
                        f"{column_count:,} cols",
                    ),
                ),
                ui.input_action_button(
                    "modal_close_config", "\u00d7", class_="modal-close-btn"
                ),
            ),
            ui.div(
                {"class": "modal-panel-body"},
                ui.div(
                    {"class": "include-toggle-row"},
                    ui.div(
                        ui.strong("Include in Analysis"),
                        ui.p(
                            {"class": "hint"},
                            "Enable this dataset for the current workspace.",
                        ),
                    ),
                    ui.input_switch(
                        "modal_include_dataset",
                        label=None,
                        value=bool(dataset.get("selected")),
                    ),
                ),
                ui.div(
                    {"class": "modal-section"},
                    ui.div({"class": "group-header"}, "Dataset Metadata Filters"),
                    *option_sections,
                ),
            ),
            ui.div(
                {"class": "modal-panel-footer"},
                ui.input_action_button(
                    "modal_clear_filters",
                    "Clear",
                    class_="btn btn-sm btn-outline-secondary",
                ),
                ui.input_action_button(
                    "modal_cancel_filters", "Cancel", class_="btn btn-sm btn-secondary"
                ),
                ui.input_action_button(
                    "modal_apply_filters",
                    "Apply Filters",
                    class_="btn btn-sm btn-primary",
                ),
            ),
        ),
    )


__all__ = ["render_dataset_config_modal"]
