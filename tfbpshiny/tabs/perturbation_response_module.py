from logging import Logger

import pandas as pd
from shiny import Inputs, Outputs, Session, module, reactive, ui

from ..misc.binding_perturbation_upset_module import upset_plot_server, upset_plot_ui
from ..misc.correlation_plot_module import (
    correlation_matrix_server,
    correlation_matrix_ui,
)

col_widths = {
    "xxl": (7, 5),
    "xl": (7, 5),
    "lg": (12, 12),
    "md": (12, 12),
    "sm": (12, 12),
    "xs": (12, 12),
}


@module.ui
def perturbation_response_ui():
    return (
        ui.layout_columns(
            upset_plot_ui("perturbation_response_upset"),
            correlation_matrix_ui("perturbation_corr_matrix"),
            col_widths=col_widths,  # type: ignore
        ),
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
