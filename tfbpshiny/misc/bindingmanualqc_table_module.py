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
    """
    This function produces the reactive/render functions necessary to producing the
    binding manual quality control table. All arguments must be passed as keyword
    arguments.

    :param bindingmanualqc_df: the filtered bindingmanualqc_df based on the selected
        regulator
    :param logger: A logger object
    :return: None

    """

    @render.data_frame
    def bindingmanualqc_table():
        df_local = bindingmanualqc_df()  # type: ignore
        if df_local.empty:
            return pd.DataFrame()

        return df_local

    return None
