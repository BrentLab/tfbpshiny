from logging import Logger

import plotly.express as px
from shiny import Inputs, Outputs, Session, module, reactive
from shinywidgets import output_widget, render_plotly


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
    @output(id="rank_response_plot")
    @render_plotly
    def rank_response_plot():
        df = rank_response_metadata.result()
        if df.empty or not {"rank_25", "expression_source", "binding_source"}.issubset(
            df.columns
        ):
            return px.scatter(title="No data available")

        fig = px.box(
            df,
            x="binding_source",
            y="rank_25",
            color="binding_source",
            facet_col="expression_source",
            points="outliers",
        )

        fig.update_layout(
            margin=dict(l=20, r=20, t=30, b=30),
            height=600,
            boxmode="group",
            yaxis_title="Rank 25 Response",
        )

        fig.update_yaxes(matches=None)

        return fig
