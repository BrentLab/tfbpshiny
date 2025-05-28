import logging

import pandas as pd
import plotly.express as px
from plotly.graph_objects import Figure

from .plot_formatter import plot_formatter
from .rename_dataframe_data_sources import rename_dataframe_data_sources
from .source_name_lookup import get_source_name_dict

logger = logging.getLogger("shiny")


def create_distribution_plot(
    df: pd.DataFrame,
    y_column: str,
    y_axis_title: str,
    **kwargs,
) -> Figure:
    """
    Create consistently formatting distribution plots for DTO empirical pvalue, rank
    response 25 and univariate pvalue.

    :param df: DataFrame containing the data to plot. Must have at minimum the columns
        'binding_source', 'expression_source' and the y_column
    :param y_column: The column name in the DataFrame to plot on the y-axis
    :param y_axis_title: The title for the y-axis
    :param kwargs: Additional keyword arguments to pass to plot_formatter
    :return: A Plotly Figure object containing the distribution plot
    :raises ValueError: If the DataFrame does not contain the required columns
    :raises TypeError: If the input df is not a pandas DataFrame or y_column is not
        numeric

    """
    # check that y_column, binding_source and expression_source are in the DataFrame
    if not all(
        col in df.columns for col in [y_column, "binding_source", "expression_source"]
    ):
        logger.error(
            "DataFrame must contain columns: "
            f"{y_column}, binding_source, expression_source"
        )
        raise ValueError(
            f"DataFrame must contain columns: "
            f"{y_column}, binding_source, expression_source"
        )
    # check that y_column is numeric
    if not pd.api.types.is_numeric_dtype(df[y_column]):
        logger.error(f"Column {y_column} must be numeric")
        raise TypeError(f"Column {y_column} must be numeric")

    binding_source_dict = get_source_name_dict("binding")
    perturbation_source_dict = get_source_name_dict("perturbation_response")

    if not isinstance(df, pd.DataFrame):
        logger.error("Input df is not a pandas DataFrame")
        raise TypeError("Input df must be a pandas DataFrame")

    df_renamed = rename_dataframe_data_sources(df)

    # Determine consistent order from dict values
    binding_levels = list(binding_source_dict.values())
    perturbation_levels = list(perturbation_source_dict.values())

    # Optional override by user
    category_orders = {
        "binding_source": binding_levels,
        "expression_source": perturbation_levels,
    }

    # Set fixed colors by binding source name
    color_palette = px.colors.qualitative.Vivid
    color_discrete_map = {
        name: color_palette[i % len(color_palette)]
        for i, name in enumerate(binding_levels)
    }

    # Create plot
    fig = px.box(
        df_renamed,
        x="binding_source",
        y=y_column,
        color="binding_source",
        facet_col="expression_source",
        facet_col_spacing=0.04,
        points="outliers",
        category_orders=category_orders,
        color_discrete_map=color_discrete_map,
    )

    return plot_formatter(fig, "Binding Data Source", y_axis_title, **kwargs)
