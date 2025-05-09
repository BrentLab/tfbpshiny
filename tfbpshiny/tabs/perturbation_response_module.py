from logging import Logger

import pandas as pd
from shiny import Inputs, Outputs, Session, module, reactive, ui

from ..misc.binding_perturbation_upset_module import upset_plot_server, upset_plot_ui
from ..misc.correlation_plot_module import (
    correlation_matrix_server,
    correlation_matrix_ui,
)


@module.ui
def perturbation_response_ui():
    return ui.div(
        ui.div(
            # Outer flex container: two columns
            ui.div(
                # Left column: UpSet + description
                ui.div(
                    # UpSet Plot Card
                    ui.card(
                        ui.card_header("Perturbation Response UpSet Plot"),
                        ui.card_body(upset_plot_ui("perturbation_response_upset")),
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
                            "across multiple perturbation response datasets. "
                            "You can explore intersections by clicking bars or nodes. "
                            "Use this to identify regulators present in multiple "
                            "datasets or unique to one."
                        ),
                        ui.p(
                            "The correlation matrix shows similarity "
                            "between TF perturbation response profiles."
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
                        ui.card_header("Perturbation Response Correlation Matrix"),
                        ui.card_body(
                            ui.div(
                                correlation_matrix_ui("perturbation_corr_matrix"),
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
                style=(
                    "display: flex; flex-direction: row; justify-content: center; "
                    "align-items: flex-start;"
                ),
            )
        )
    )


@module.server
def perturbation_response_server(
    input: Inputs,
    output: Outputs,
    session: Session,
    *,
    pr_metadata_task: reactive.ExtendedTask,
    logger: Logger,
) -> reactive.calc:
    """
    This function produces the reactive/render functions necessary to producing the
    perturbation response upset plot and correlation matrix for the perturbation
    response data.

    :param pr_metadata_task: This is the result from a reactive.extended_task. Result
        can be retrieved with .result()
    :param logger: A logger object
    :return: A reactive.calc with the metadata filtered for the selected upset plot sets
        (note that this is not currently working b/c of something to do with the upset
        plot server)

    """

    # TODO: this should be retrieved from the db as a reactive.extended_task.
    # move it into the app.py and init function
    source_name_dict = {
        "mcisaac_oe": "mcisaac_oe",
        "kemmeren_tfko": "kemmeren_tfko",
        "hu_reimann_tfko": "hu_reimann_tfko",
    }

    # TODO: retrieving the response should be from the db as a reactive.extended_task
    tf_pr_df = pd.read_csv("tmp/shiny_data/response_data.csv")
    tf_pr_df.set_index("target_symbol", inplace=True)
    correlation_matrix_server(
        "perturbation_corr_matrix",
        tf_binding_df=tf_pr_df,
        logger=logger,
    )

    selected_pr_sets = upset_plot_server(
        "perturbation_response_upset",
        metadata_result=pr_metadata_task,
        source_name_dict=source_name_dict,
        logger=logger,
    )

    @reactive.effect
    def _():
        logger.info(f"Selected perturbation response sets: {selected_pr_sets()}")

    return selected_pr_sets
