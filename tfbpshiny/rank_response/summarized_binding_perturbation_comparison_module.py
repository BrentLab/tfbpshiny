from logging import Logger

from shiny import Inputs, Outputs, Session, module, reactive, render, req, ui

# note that this isn't part of the public API. Possibly unstable
from shiny.render._data_frame_utils._types import StyleInfo

from ..utils.apply_column_names import apply_column_names
from ..utils.rename_dataframe_data_sources import rename_dataframe_data_sources
from ..utils.safe_percentage_format import safe_percentage_format
from ..utils.safe_sci_notatation import safe_sci_notation

# Summarized binding-perturbation comparison table column metadata for selection
SUMMARIZED_BINDING_PERTURBATION_COLUMN_METADATA = {
    "single_binding": (
        "Single Binding",
        "Unique ID for a single replicate; NA if composite.",
    ),
    "composite_binding": (
        "Composite Binding",
        "Unique ID for composite replicate; NA if single.",
    ),
    "expression_time": (
        "Expression Time",
        "Time point of McIsaac overexpression assay.",
    ),
    "univariate_rsquared": (
        "R²",
        "R² of model perturbed ~ binding.",
    ),
    "univariate_pvalue": (
        "P-value",
        "P-value of model perturbed ~ binding.",
    ),
    "binding_rank_threshold": (
        "Binding Rank Threshold",
        "binding rank with most significant DTO overlap.",
    ),
    "perturbation_rank_threshold": (
        "Perturbation Rank Threshold",
        "perturbation rank with most significant DTO overlap.",
    ),
    "binding_set_size": (
        "Binding Set Size",
        (
            "Gene count in binding set in DTO overlap. "
            "May be larger than rank due to ties."
        ),
    ),
    "perturbation_set_size": (
        "Perturbation Set Size",
        (
            "Gene count in perturbation set in DTO overlap. "
            "May be larger than rank due to ties."
        ),
    ),
    "dto_fdr": (
        "DTO FDR",
        "False discovery rate from DTO.",
    ),
    "dto_empirical_pvalue": (
        "DTO Empirical P-value",
        "Empirical p-value from DTO.",
    ),
    "rank_25": (
        "Rank at 25",
        "Responsive fraction in top 25 bound genes.",
    ),
    "rank_50": (
        "Rank at 50",
        "Responsive fraction in top 50 bound genes.",
    ),
}

# Convert to dictionary: {value: HTML label}
SUMMARIZED_BINDING_PERTURBATION_CHOICES_DICT = {
    key: ui.span(label, title=desc)
    for key, (label, desc) in SUMMARIZED_BINDING_PERTURBATION_COLUMN_METADATA.items()
}

# Default selection for summarized binding-perturbation comparison table
DEFAULT_SUMMARIZED_BINDING_PERTURBATION_COLUMNS = [
    "univariate_rsquared",
    "dto_fdr",
    "dto_empirical_pvalue",
    "rank_25",
]


@module.ui
def summarized_binding_perturbation_comparison_ui():
    return ui.output_data_frame("summarized_binding_perturbation_comparison")


@module.server
def summarized_binding_perturbation_comparison_server(
    input: Inputs,
    output: Outputs,
    session: Session,
    *,
    rr_metadata: reactive.calc,
    expression_source: str,
    selected_promotersetsigs: reactive.value,
    selected_columns: reactive.calc,
    logger: Logger,
) -> None:
    """
    Server for expression source specific summarized binding-perturbation comparison.

    :param rr_metadata: Complete rank response metadata
    :param expression_source: The specific expression source to filter for
    :param selected_promotersetsigs: Reactive value containing selected promotersetsigs
    :param selected_columns: Reactive calc containing selected columns to display
    :param logger: Logger object

    """

    @render.data_frame
    def summarized_binding_perturbation_comparison():
        req(rr_metadata)
        req(selected_columns)

        df_local = rr_metadata().copy()  # type: ignore

        # Filter for specific expression source
        df_local = df_local[df_local["expression_source"] == expression_source]

        # Get selected promotersetsigs for highlighting
        selected_promotersetsigs_local = selected_promotersetsigs.get()

        # Get selected columns from the accordion
        selected_cols = selected_columns()  # type: ignore

        # Always include promotersetsig (needed for highlighting logic)
        columns_to_show = ["promotersetsig"] + [
            col for col in selected_cols if col != "promotersetsig"
        ]

        # Filter to only show columns that exist in the dataframe and are selected
        available_columns = [col for col in columns_to_show if col in df_local.columns]

        if available_columns:
            df_local = df_local[available_columns]

        df_local = rename_dataframe_data_sources(df_local)

        sci_notation_cols = [
            "univariate_pvalue",
            "univariate_rsquared",
            "dto_fdr",
            "dto_empirical_pvalue",
            "random_expectation",
        ]

        percentage_cols = [
            "rank_25",
            "rank_50",
        ]

        # Format scientific notation columns
        existing_sci_cols = [
            col for col in sci_notation_cols if col in df_local.columns
        ]
        if existing_sci_cols:
            df_local[existing_sci_cols] = df_local[existing_sci_cols].applymap(
                safe_sci_notation
            )

        # Format percentage columns
        existing_percentage_cols = [
            col for col in percentage_cols if col in df_local.columns
        ]
        if existing_percentage_cols:
            df_local[existing_percentage_cols] = df_local[
                existing_percentage_cols
            ].applymap(safe_percentage_format)

        # Apply friendly column names from metadata
        df_local = apply_column_names(
            df_local, SUMMARIZED_BINDING_PERTURBATION_COLUMN_METADATA
        )

        df_local.reset_index(drop=True, inplace=True)

        # Create styles for highlighting rows that match selection
        styles: StyleInfo | None = None
        if selected_promotersetsigs_local:
            promotersetsig_col = "id"
            if promotersetsig_col in df_local.columns:
                matching_rows = df_local[
                    df_local[promotersetsig_col].isin(selected_promotersetsigs_local)
                ].index.tolist()

                if matching_rows:
                    styles = {
                        "rows": matching_rows,
                        "cols": list(range(len(df_local.columns))),
                        "style": {"background-color": "#e6fffa"},
                    }

        return render.DataGrid(
            df_local,
            selection_mode="none",
            styles=styles,
        )
