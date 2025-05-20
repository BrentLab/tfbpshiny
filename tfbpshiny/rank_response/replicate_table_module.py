from logging import Logger

import pandas as pd
from shiny import Inputs, Outputs, Session, module, reactive, render, ui

from ..utils.rename_dataframe_data_sources import rename_dataframe_data_sources


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
):
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
        if df_local.empty:
            return pd.DataFrame()

        return df_local

    return None
