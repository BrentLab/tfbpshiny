from logging import Logger

from shiny import Inputs, Outputs, Session, module, reactive, render, ui

from ..utils.rename_dataframe_data_sources import rename_dataframe_data_sources
from ..utils.safe_sci_notatation import safe_sci_notation


@module.ui
def rank_response_replicate_table_ui():
    return ui.output_data_frame("rank_response_replicate_table")


@module.server
def rank_response_replicate_table_server(
    input: Inputs,
    output: Outputs,
    session: Session,
    *,
    rr_metadata: reactive.calc,
    logger: Logger,
) -> reactive.calc:
    """
    This function produces the reactive/render functions necessary to producing the rank
    response replicate table. All arguments must be passed as keyword arguments.

    :param rr_metadata: This is the filtered rank response metadata based on the
        selected TF and selected columns.
    :param logger: A logger object
    :return: None

    """

    @render.data_frame
    def rank_response_replicate_table():
        df_local = rr_metadata().copy()  # type: ignore
        df_local = rename_dataframe_data_sources(df_local)

        # list of numeric columns to format
        cols_to_format = [
            "univariate_pvalue",
            "univariate_rsquared",
            "dto_fdr",
            "dto_empirical_pvalue",
            "random_expectation",
            "rank_25",
            "rank_50",
        ]

        # Only apply formatting to numeric columns that exist in the DataFrame
        existing_numeric_cols = [
            col for col in cols_to_format if col in df_local.columns
        ]
        df_local[existing_numeric_cols] = df_local[existing_numeric_cols].applymap(
            safe_sci_notation
        )

        return render.DataGrid(
            df_local,
            selection_mode="rows",
        )

    def get_selected_promotersetsig():
        selected_rows = rank_response_replicate_table.cell_selection()["rows"]
        rr_local = rr_metadata()  # type: ignore
        if not selected_rows or rr_local.empty:
            return set()
        return set(rr_local.loc[list(selected_rows), "promotersetsig"])

    return get_selected_promotersetsig
