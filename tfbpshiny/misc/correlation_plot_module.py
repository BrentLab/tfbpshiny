from logging import Logger

import pandas as pd
import plotly.express as px
from shiny import Inputs, Outputs, Session, module
from shinywidgets import output_widget, render_plotly


def cluster_corr_matrix_both(corr: pd.DataFrame) -> pd.DataFrame:
    from scipy.cluster.hierarchy import leaves_list, linkage

    # Compute linkage on correlation
    linkage_matrix = linkage(corr, method="average")
    leaves = leaves_list(linkage_matrix)

    # Apply same order to both rows and columns
    ordered = corr.iloc[leaves, :].iloc[:, leaves]
    return ordered


@module.ui
def correlation_matrix_ui():
    return output_widget("correlation_matrix_plot")


@module.server
def correlation_matrix_server(
    input: Inputs,
    output: Outputs,
    session: Session,
    *,
    tf_binding_df: pd.DataFrame,
    logger: Logger,
):
    """
    This function produces the reactive/render functions necessary to producing the
    binding and perturbation response correlation matrix plot. Currently used in the
    binding and perturbation response tabs. NOTE: tf_binding_df is currently passed as a
    static dataframe -- this needs to be changed when the predictors df are retrieved
    from the db.

    :param tf_binding_df: A pandas dataframe with the binding or perturbation response
        data. The index should be the target symbol and the columns should be the
        binding or perturbation response data. NOTE the TODO in the description
    :param logger: A logger object
    :return: None

    """

    @render_plotly
    def correlation_matrix_plot():
        if tf_binding_df.empty or tf_binding_df.shape[1] < 2:
            return px.scatter(title="Not enough data to compute correlation")

        # Compute correlation matrix
        clustered_corr = cluster_corr_matrix_both(tf_binding_df.corr())

        fig = px.imshow(
            clustered_corr,
            text_auto=".2f",
            aspect="equal",
            color_continuous_scale="Blues",
            title="Clustered TF Correlation Matrix",
            zmin=0,
            zmax=1,
        )

        # Improve layout and readability
        fig.update_layout(
            title_x=0.5,
            margin=dict(l=60, r=60, t=50, b=60),
            coloraxis_colorbar=dict(
                title="Correlation",
                ticks="outside",
                tickvals=[0.0, 0.25, 0.5, 0.75, 1.0],
                tickformat=".2f",
            ),
        )

        # Improve tick labels: rotate for readability
        fig.update_xaxes(tickangle=45, tickfont=dict(size=8))
        fig.update_yaxes(tickfont=dict(size=8))

        return fig
