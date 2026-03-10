"""Modal builders for Active Set selection."""

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


def resolve_analysis_module(type_a: str, type_b: str) -> str | None:
    """Match React modal routing logic for intersection detail."""
    if type_a == "Binding" and type_b == "Binding":
        return "binding"
    if type_a == "Perturbation" and type_b == "Perturbation":
        return "perturbation"
    if (type_a == "Binding" and type_b == "Perturbation") or (
        type_a == "Perturbation" and type_b == "Binding"
    ):
        return "composite"
    if type_a == "Expression" and type_b == "Binding":
        return "binding"
    if type_a == "Binding" and type_b == "Expression":
        return "binding"
    if type_a == "Expression" and type_b == "Perturbation":
        return "perturbation"
    if type_a == "Perturbation" and type_b == "Expression":
        return "perturbation"
    return None


def render_intersection_detail_modal(details: dict[str, Any]) -> ui.Tag:
    """Render IntersectionDetailModal-like UI as an overlay panel."""
    row_dataset = details["rowDataset"]
    col_dataset = details["colDataset"]
    count = int(details.get("intersectionCount") or 0)

    row_tf_count = int(row_dataset.get("tf_count") or 0)
    col_tf_count = int(col_dataset.get("tf_count") or 0)

    row_pct = "N/A" if row_tf_count <= 0 else f"{(count / row_tf_count) * 100:.1f}%"
    col_pct = "N/A" if col_tf_count <= 0 else f"{(count / col_tf_count) * 100:.1f}%"

    target_module = resolve_analysis_module(
        str(row_dataset.get("type", "Expression")),
        str(col_dataset.get("type", "Expression")),
    )

    target_labels = {
        "binding": "Binding Analysis",
        "perturbation": "Perturbation Analysis",
        "composite": "Binding & Perturbation",
    }
    target_label = (
        target_labels.get(target_module, "Analysis") if target_module else "Analysis"
    )

    return ui.div(
        {"class": "modal-overlay"},
        ui.div(
            {"class": "modal-card modal-medium"},
            ui.div(
                {"class": "modal-panel-header"},
                ui.h3("Intersection Analysis"),
                ui.input_action_button(
                    "modal_close_intersection", "\u00d7", class_="modal-close-btn"
                ),
            ),
            ui.div(
                {"class": "modal-panel-body"},
                ui.div(
                    {"class": "intersection-dataset-row"},
                    ui.div(
                        {"class": "intersection-dataset-card"},
                        ui.div(
                            {"class": "intersection-dataset-value"}, f"{row_tf_count:,}"
                        ),
                        ui.div(str(row_dataset.get("name", "Dataset A"))),
                    ),
                    ui.div({"class": "intersection-vs"}, "VS"),
                    ui.div(
                        {"class": "intersection-dataset-card"},
                        ui.div(
                            {"class": "intersection-dataset-value"}, f"{col_tf_count:,}"
                        ),
                        ui.div(str(col_dataset.get("name", "Dataset B"))),
                    ),
                ),
                ui.div(
                    {"class": "intersection-result-card"},
                    ui.div({"class": "intersection-result-label"}, "Common TFs"),
                    ui.div({"class": "intersection-result-value"}, f"{count:,}"),
                    ui.div(
                        {"class": "intersection-result-meta"},
                        f"{row_pct} of A · {col_pct} of B",
                    ),
                ),
            ),
            ui.div(
                {"class": "modal-panel-footer"},
                ui.input_action_button(
                    "modal_close_intersection_secondary",
                    "Close",
                    class_="btn btn-sm btn-secondary",
                ),
                (
                    ui.input_action_button(
                        "modal_open_analysis",
                        f"Open in {target_label}",
                        class_="btn btn-sm btn-primary",
                    )
                    if target_module
                    else ui.span()
                ),
            ),
        ),
    )
