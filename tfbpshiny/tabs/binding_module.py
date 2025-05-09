from logging import Logger

import pandas as pd
from shiny import Inputs, Outputs, Session, module, reactive, ui

from ..misc.binding_perturbation_upset_module import upset_plot_server, upset_plot_ui
from ..misc.correlation_plot_module import (
    correlation_matrix_server,
    correlation_matrix_ui,
)
from ..utils.source_name_lookup import get_source_name_dict


@module.ui
def binding_ui():
    return ui.div(
        ui.div(
            # Outer flex container: two columns
            ui.div(
                # Left column: UpSet + description
                ui.div(
                    # UpSet Plot Card
                    ui.card(
                        ui.card_header("Binding UpSet Plot"),
                        ui.card_body(upset_plot_ui("binding_upset")),
                        ui.card_footer(
                            ui.p(
                                "Click any one of the sets to show what proportion of "
                                "the regulators in the selected set are also present "
                                "in the other sets.",
                                class_="text-muted",
                            ),
                        ),
                    ),
                    ui.div(
                        ui.h3("Description"),
                        ui.p(
                            "The UpSet plot displays shared regulators"
                            "across multiple binding datasets. You can explore"
                            "intersections by clicking bars or nodes. Use this"
                            "to identify regulators present in multiple datasets"
                            "or unique to one."
                        ),
                        ui.p(
                            "The correlation matrix shows similarity "
                            "between TF binding profiles."
                        ),
                        style="margin-top: 1rem; width: 100%; max-width: 1200px;",
                    ),
                    style=(
                        "width: 1200px; min-height: 500px; "
                        "margin-right: 2rem; flex-shrink: 0;"
                    ),
                ),
                # Right column: Correlation matrix
                ui.div(
                    ui.card(
                        ui.card_header("Binding Correlation Matrix"),
                        ui.card_body(
                            ui.div(
                                correlation_matrix_ui("binding_corr_matrix"),
                                style=(
                                    "width: 450px; height: 450px;"
                                    "display: flex; align-items: center; "
                                    "justify-content: center;"
                                ),
                            ),
                            style="display: flex; justify-content: center; "
                            "align-items: center;",
                        ),
                        ui.card_footer(
                            ui.p(
                                "Click and drag to zoom in on a specific region of the "
                                "correlation matrix. Double click to reset the zoom.",
                                class_="text-muted",
                            ),
                        ),
                    ),
                    style="flex-shrink: 0; display: flex; justify-content: center;",
                ),
                style="display: flex; flex-direction: row; justify-content: center; "
                "align-items: flex-start;",
            )
        )
    )


@module.server
def binding_server(
    input: Inputs,
    output: Outputs,
    session: Session,
    *,
    binding_metadata_task: reactive.ExtendedTask,
    logger: Logger,
) -> reactive.calc:
    """
    This function produces the reactive/render functions necessary to producing the
    binding upset plot and correlation matrix.

    :param binding_metadata_task: This is the result from a reactive.extended_task.
        Result can be retrieved with .result()
    :param logger: A logger object
    :return: A reactive.calc with the metadata filtered for the selected upset plot sets
        (note that this is not currently working b/c of something to do with the upset
        plot server)

    """

    selected_binding_sets = upset_plot_server(
        "binding_upset",
        metadata_result=binding_metadata_task,
        source_name_dict=get_source_name_dict("perturbation_response"),
        logger=logger,
    )

    # TODO: retrieving the predictors should be from the db as a reactive.extended_task
    tf_binding_df = pd.read_csv("tmp/shiny_data/cc_predictors_normalized.csv")
    tf_binding_df.set_index("target_symbol", inplace=True)
    correlation_matrix_server(
        "binding_corr_matrix",
        tf_binding_df=tf_binding_df,
        logger=logger,
    )

    return selected_binding_sets
