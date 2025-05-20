import logging

import pandas as pd
import plotly.express as px
from plotly.graph_objects import Figure

from .plot_formatter import apply_plot_formatter
from .rename_dataframe_data_sources import rename_dataframe_data_sources

logger = logging.getLogger("shiny")


def create_distribution_plot(
    df: pd.DataFrame,
    y_column: str,
    y_axis_title: str,
    category_orders: dict[str, list] | None = None,
) -> Figure:
    """
    Create a standardized distribution plot.

    :param df: DataFrame with the plot data
    :param y_column: Column name to plot on y-axis
    :param y_axis_title: Title for the y-axis
    :param category_orders: Optional dict of category orders
    :return: A formatted plotly figure
    :raises TypeError: If df is not a pandas DataFrame

    """
    if not isinstance(df, pd.DataFrame):
        logger.error("Input df is not a pandas DataFrame")
        raise TypeError("Input df must be a pandas DataFrame")

    df_renamed = rename_dataframe_data_sources(df)

    # Default category orders if not provided
    if category_orders is None:
        category_orders = {
            "expression_source": ["Overexpression", "2014 TFKO", "2007 TFKO"]
        }

    # Create the plot
    fig = px.box(
        df_renamed,
        x="binding_source",
        y=y_column,
        color="binding_source",
        facet_col="expression_source",
        points="outliers",
        category_orders=category_orders,
    )

    return apply_plot_formatter(fig, y_axis_title)
