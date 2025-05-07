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
def binding_ui():
    return (
        ui.layout_columns(
            upset_plot_ui("binding_upset"),
            correlation_matrix_ui("binding_corr_matrix"),
            col_widths=col_widths,  # type: ignore
        ),
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

    # TODO: this should be retrieved from the db as a reactive.extended_task.
    # move it into the app.py and init function
    source_name_dict = {
        "harbison_chip": "2004 ChIP-chip",
        "chipexo_pugh_allevents": "2021 ChIP-exo",
        "brent_nf_cc": "Calling Cards",
    }

    selected_binding_sets = upset_plot_server(
        "binding_upset",
        metadata_result=binding_metadata_task,
        source_name_dict=source_name_dict,
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
