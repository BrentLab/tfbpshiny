from logging import Logger

import pandas as pd
from shiny import Inputs, Outputs, Session, module, reactive, render, ui

from ..utils.format_number_for_display import format_to_sci_notation
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
    rr_metadata: reactive.Value,
    logger: Logger,
):
    """
    This function produces the reactive/render functions necessary to producing the rank
    response replicate table.

    :param rr_metadata: A reactive.Value containing the DataFrame with rank response
        metadata, likely including pvalue, response_ratio, etc.
    :param logger: A logger object
    :return: None

    """

    @output
    @render.data_frame
    def rank_response_replicate_table():
        meta_df = rr_metadata().copy()
        if meta_df is None or meta_df.empty:
            logger.info("Rank response metadata is empty. Returning empty table.")
            return pd.DataFrame()

        df_local = meta_df.copy()

        # Rename source columns if they exist
        if "binding_source" in df_local.columns:
            binding_source_name_dict = get_source_name_dict("binding")
            df_local["binding_source"] = df_local["binding_source"].map(
                lambda x: binding_source_name_dict.get(x, x)
            )
        # if "expression_source" is in df_local.columns, then use
        # get_source_name_dict("perturbation_response") to rename the levels in the
        # column from the dict keys to the dict values. If a key doesn't exist,
        # use the current entry
        if "expression_source" in df_local.columns:
            expression_source_name_dict = get_source_name_dict("perturbation_response")
            df_local["expression_source"] = df_local["expression_source"].map(
                lambda x: expression_source_name_dict.get(x, x)
            )

        # Identify numerical columns to format
        # Adjust this list based on the actual columns in your rr_metadata DataFrame
        cols_to_format = [
            "univariate_pvalue",
            "univariate_rsquared",
            "dto_fdr",
            "dto_empirical_pvalue",
            "random_expectation",
            "rank_25",
            "rank_50",
        ]

        for col in cols_to_format:
            if col in df_local.columns:
                # Ensure the column is numeric before attempting to format
                # to avoid errors if it's already string or another type.
                # format_to_sci_notation will also raise TypeError for
                # non-numerics in list.
                try:
                    # Convert to numeric, coercing errors to NaN,
                    # then drop NaNs for formatting
                    numeric_series = pd.to_numeric(df_local[col], errors="coerce")
                    # Apply formatting only to non-NaN values
                    formatted_values = numeric_series.dropna().apply(
                        format_to_sci_notation
                    )
                    # Update the original DataFrame, keeping NaNs as they were
                    # or you can fill them with a default value
                    df_local[col] = numeric_series.astype(
                        object
                    )  # Ensure column can hold strings and NaNs
                    df_local.loc[formatted_values.index, col] = formatted_values

                except Exception as e:
                    logger.warning(
                        f"Could not format column '{col}' "
                        f"in rank_response_replicate_table. Error: {e}"
                    )
            else:
                logger.debug(
                    f"Column '{col}' not found for formatting "
                    f"in rank_response_replicate_table."
                )

        logger.info("Rank response replicate table processed for display.")
        return df_local

    # The server function in Shiny modules should typically return something if it's
    # providing outputs or reactives to be used by other modules,
    # but for a simple table display module, returning None if it only defines
    # outputs is common. If rr_metadata itself is the primary output that other
    # modules might consume *after* this server logic, that would be different.
    # Based on the original snippet, it seems this module primarily *renders* the table.
    return None
