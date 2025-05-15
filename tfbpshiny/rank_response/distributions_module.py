from logging import Logger

import plotly.express as px
from shiny import Inputs, Outputs, Session, module, reactive
from shinywidgets import output_widget, render_plotly

from ..utils.source_name_lookup import get_source_name_dict


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
        df = rank_response_metadata.result().copy()
        if df.empty or not {"rank_25", "expression_source", "binding_source"}.issubset(
            df.columns
        ):
            return px.scatter(title="No data available")

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

        fig = px.box(
            df,
            x="binding_source",
            y="rank_25",
            color="binding_source",
            facet_col="expression_source",
            points="outliers",
            category_orders={
                "expression_source": ["Overexpression", "2014 TFKO", "2007 TFKO"]
            },
        )

        # Modified layout with better legend positioning
        fig.update_layout(
            # Increase right margin significantly to make room for legend
            margin=dict(l=40, r=120, t=50, b=80),
            height=450,
            boxmode="group",
            yaxis_title="Rank 25 Response",
            legend=dict(
                orientation="v",
                yanchor="top",
                y=0.99,
                xanchor="right",
                x=1.3,  # Move further right (was 1.15)
                bgcolor="rgba(255, 255, 255, 0.8)",
                bordercolor="rgba(0, 0, 0, 0.2)",
                borderwidth=1,
            ),
            autosize=True,
        )

        # Better handling of facet labels
        fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))

        # Ensure axes don't get cut off
        fig.update_xaxes(automargin=True)
        fig.update_yaxes(automargin=True, matches=None)

        return fig
