from logging import Logger

import plotly.express as px
from shiny import Inputs, Outputs, Session, module, reactive
from shinywidgets import output_widget, render_plotly

from ..misc.generic_distribution_plot import create_distribution_plot


@module.ui
def rank_response_distributions_ui():
    return output_widget("rank_response_plot")


@module.server
def rank_response_distributions_server(
    input: Inputs,
    output: Outputs,
    session: Session,
    *,
    rank_response_metadata: reactive.ExtendedTask,
    logger: Logger,
):
    """
    This function produces the reactive/render functions necessary to producing the rank
    response distributions plot.

    :param rank_response_metadata: This is the result from a reactive.extended_task.
        Result can be retrieved with .result()
    :param logger: A logger object
    :return: None

    """

    @output(id="rank_response_plot")
    @render_plotly
    def rank_response_plot():
        metadata = rank_response_metadata.result()
        if metadata.empty:
            return px.scatter(title="No data to plot")

        return create_distribution_plot(metadata, "rank_25", "Rank Response P-value")
