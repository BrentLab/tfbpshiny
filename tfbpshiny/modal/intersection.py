"""Intersection detail modal UI and analysis module routing."""

from __future__ import annotations

from typing import Any

from shiny import ui


def resolve_analysis_module(type_a: str, type_b: str) -> str | None:
    """Match React modal routing logic for intersection detail."""
    if type_a == "Binding" and type_b == "Binding":
        return "binding"
    if type_a == "Perturbation" and type_b == "Perturbation":
        return "perturbation"
    if (type_a == "Binding" and type_b == "Perturbation") or (
        type_a == "Perturbation" and type_b == "Binding"
    ):
        return "comparison"
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
        "comparison": "Binding & Perturbation",
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


__all__ = ["render_intersection_detail_modal", "resolve_analysis_module"]
