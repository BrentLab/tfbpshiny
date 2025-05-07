from logging import Logger

import pandas as pd
from shiny import Inputs, Outputs, Session, module, reactive, render, ui


@module.ui
def bindingmanualqc_table_ui():
    return ui.output_data_frame("bindingmanualqc_table")


@module.server
def bindingmanualqc_table_server(
    input: Inputs,
    output: Outputs,
    session: Session,
    *,
    bindingmanualqc_df: reactive.calc,
    logger: Logger,
):
    @render.data_frame
    def bindingmanualqc_table():
        df_local = bindingmanualqc_df()
        if df_local.empty:
            return pd.DataFrame()

        return df_local

    return None
