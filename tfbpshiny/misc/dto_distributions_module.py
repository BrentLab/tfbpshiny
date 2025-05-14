from logging import Logger

import pandas as pd
import plotly.express as px
from shiny import Inputs, Outputs, Session, module, reactive
from shinywidgets import output_widget, render_widget

from ..utils.source_name_lookup import get_source_name_dict


@module.ui
def dto_distributions_ui():
    return output_widget("dto_plot")


@module.server
def dto_distributions_server(
    input: Inputs,
    output: Outputs,
    session: Session,
    *,
    rank_response_metadata: reactive.ExtendedTask,
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
    @render_widget
    def dto_plot():
        df = rank_response_metadata.result()
        if df.empty or not {
            "expression_source",
            "binding_source",
            "dto_empirical_pvalue",
            "dto_fdr",
        }.issubset(df.columns):
            return px.scatter(title="No data to plot")  # fallback empty plot

            # if "binding_source" is in df_local.columns, then use
        # get_source_name_dict("binding") to rename the levels in the column from
        # the dict keys to the dict values. If a key doesn't exist, use the current
        # entry
        if "binding_source" in df.columns:
            source_name_dict = get_source_name_dict("binding")
            df["binding_source"] = df["binding_source"].map(
                lambda x: source_name_dict.get(x, x)
            )
        # if "expression_source" is in df_local.columns, then use
        # get_source_name_dict("perturbation_response") to rename the levels
        # in the column from the dict keys to the dict values. If a key doesn't
        # exist, use the current entry
        if "expression_source" in df.columns:
            source_name_dict = get_source_name_dict("perturbation_response")
            df["expression_source"] = df["expression_source"].map(
                lambda x: source_name_dict.get(x, x)
            )

        # Reshape to long format for faceting
        df_long = pd.melt(
            df,
            id_vars=["expression_source", "binding_source"],
            value_vars=["dto_empirical_pvalue", "dto_fdr"],
            var_name="metric",
            value_name="value",
        )

        fig = px.box(
            df_long,
            x="binding_source",
            y="value",
            color="binding_source",
            facet_col="expression_source",
            facet_row="metric",
            points="outliers",
            category_orders={
                "metric": ["dto_empirical_pvalue", "dto_fdr"],
            },
        )

        fig.update_layout(
            margin=dict(l=20, r=20, t=30, b=30),
            height=600,
            boxmode="group",
        )

        fig.update_yaxes(matches=None)

        return fig
