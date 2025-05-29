from logging import Logger

from shiny import Inputs, Outputs, Session, module, reactive, render, req, ui

from ..utils.rename_dataframe_data_sources import rename_dataframe_data_sources
from ..utils.safe_sci_notatation import safe_sci_notation


@module.ui
def expression_source_table_ui():
    return ui.output_data_frame("expression_source_table")


@module.server
def expression_source_table_server(
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
    Server for expression source specific table.

    :param rr_metadata: Complete rank response metadata
    :param expression_source: The specific expression source to filter for
    :param selected_promotersetsigs: Reactive value containing selected promotersetsigs
    :param selected_columns: Reactive calc containing selected columns to display
    :param logger: Logger object

    """

    @render.data_frame
    def expression_source_table():
        req(rr_metadata)
        req(selected_columns)

        df_local = rr_metadata().copy()  # type: ignore

        # Filter for specific expression source
        df_local = df_local[df_local["expression_source"] == expression_source]

        # Get selected promotersetsigs for highlighting
        selected_promotersetsigs_local = selected_promotersetsigs.get()

        # Get selected columns from the accordion
        selected_cols = selected_columns()

        # Always include promotersetsig (needed for highlighting logic)
        columns_to_show = ["promotersetsig"] + [
            col for col in selected_cols if col != "promotersetsig"
        ]

        # Filter to only show columns that exist in the dataframe and are selected
        available_columns = [col for col in columns_to_show if col in df_local.columns]

        if available_columns:
            df_local = df_local[available_columns]

        df_local = rename_dataframe_data_sources(df_local)

        # Format numeric columns
        cols_to_format = [
            "univariate_pvalue",
            "univariate_rsquared",
            "dto_fdr",
            "dto_empirical_pvalue",
            "random_expectation",
            "rank_25",
            "rank_50",
        ]

        existing_numeric_cols = [
            col for col in cols_to_format if col in df_local.columns
        ]
        if existing_numeric_cols:
            df_local[existing_numeric_cols] = df_local[existing_numeric_cols].applymap(
                safe_sci_notation
            )

        df_local.reset_index(drop=True, inplace=True)

        # Create styles for highlighting rows that match selection
        styles = None
        if selected_promotersetsigs_local:
            matching_rows = df_local[
                df_local["promotersetsig"].isin(selected_promotersetsigs_local)
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
            styles=[styles] if styles else [],
        )
