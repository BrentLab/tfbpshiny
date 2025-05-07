from logging import Logger

import pandas as pd
from shiny import Inputs, Outputs, Session, module, reactive, render, ui


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
    @render.data_frame
    def rank_response_replicate_table():
        df_local = rr_metadata()
        if df_local.empty:
            return pd.DataFrame()

        return df_local

    return None
