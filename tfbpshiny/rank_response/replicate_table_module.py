from logging import Logger

import pandas as pd
from shiny import Inputs, Outputs, Session, module, reactive, render, ui

from ..utils.source_name_lookup import get_source_name_dict

# TODO: consider generalizing this for any dataframe. There is nothing specific to
# rank_response_replicate_table in this module.


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
        df_local = rr_metadata()
        # if "binding_source" is in df_local.columns, then use
        # get_source_name_dict("binding") to rename the levels in the column from
        # the dict keys to the dict values. If a key doesn't exist, use the current
        # entry
        if "binding_source" in df_local.columns:
            source_name_dict = get_source_name_dict("binding")
            df_local["binding_source"] = df_local["binding_source"].map(
                lambda x: source_name_dict.get(x, x)
            )
        # if "expression_source" is in df_local.columns, then use
        # get_source_name_dict("expression") to rename the levels in the column from
        # the dict keys to the dict values. If a key doesn't exist, use the current
        # entry
        if "expression_source" in df_local.columns:
            source_name_dict = get_source_name_dict("perturbation_response")
            df_local["expression_source"] = df_local["expression_source"].map(
                lambda x: source_name_dict.get(x, x)
            )
        if df_local.empty:
            return pd.DataFrame()

        return df_local

    return None
