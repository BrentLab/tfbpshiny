from logging import Logger

import plotly.express as px
from shiny import Inputs, Outputs, Session, module, reactive
from shinywidgets import output_widget, render_plotly

from ..utils.create_distribution_plot import create_distribution_plot
from ..utils.neg_log10_transform import neg_log10_transform


@module.ui
def dto_distributions_ui():
    return output_widget("dto_plot")


@module.server
def dto_distributions_server(
    input: Inputs,
    output: Outputs,
    session: Session,
    *,
    rank_response_metadata: reactive.calc,
    logger: Logger,
):
    """
    This function produces the reactive/render functions necessary to producing the dto
    distributions plot.

    :param rank_response_metadata: This is the result from a reactive.extended_task.
        Result can be retrieved with .result()
    :param logger: A logger object
    :return: None

    """

    @output(id="dto_plot")
    @render_plotly
    def dto_plot():
        metadata = rank_response_metadata()
        if metadata.empty:
            return px.scatter(title="No data to plot")

        na_mask = metadata["dto_empirical_pvalue"].isna()
        if na_mask.any():
            cols_to_show = [
                "regulator_symbol",
                "binding_source",
                "expression_source",
                "dto_empirical_pvalue",
            ]
            logger.info(
                f"DTO Empirical P-value contains NA values. {na_mask.sum()} rows"
            )
            logger.debug(
                "DTO Empirical P-value contains NA values. "
                "These will be removed from the plot:\n%s",
                metadata.loc[na_mask, cols_to_show].drop_duplicates(),
            )
            metadata = metadata.loc[~na_mask].copy()

        metadata.loc[:, "dto_empirical_pvalue"] = neg_log10_transform(
            metadata.loc[:, "dto_empirical_pvalue"]
        )

        return create_distribution_plot(
            metadata, "dto_empirical_pvalue", "-log10(DTO Empirical P-value)"
        )
