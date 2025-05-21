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
        points="outliers",
        category_orders=category_orders,
        color_discrete_map=color_discrete_map,
    )

    return plot_formatter(fig, y_axis_title, **kwargs)
