from logging import Logger

from shiny import Inputs, Outputs, Session, module, reactive, ui

from ..misc.dto_distributions_module import (
    dto_distributions_server,
    dto_distributions_ui,
)
from ..rank_response.distributions_module import (
    rank_response_distributions_server,
    rank_response_distributions_ui,
)

_init_rr_choices = [
    "promotersetsig",
    "expression",
    "binding_source",
    "expression_source",
    "univariate_pvalue",
    "univariate_rsquared",
    "dto_fdr",
    "dto_empirical_pvalue",
    "rank_25",
    "rank_50",
    "genomic_inserts",
    "mito_inserts",
    "plasmid_inserts",
]

_init_bindingmanualqc_choices = [
    "promotersetsig",
    "dto_status",
    "rank_response_status",
]


@module.ui
def all_regulator_compare_ui():
    return ui.card(
        rank_response_distributions_ui("rank_response_distributions"),
        dto_distributions_ui("dto_distributions"),
        style="max-width: 100%; overflow-x: auto;",
    )


@module.server
def all_regulator_compare_server(
    input: Inputs,
    output: Outputs,
    session: Session,
    *,
    rank_response_metadata: reactive.ExtendedTask,
    bindingmanualqc_result: reactive.ExtendedTask,
    logger: Logger,
):
    """
    This produces the reactive/render functions necessary to producing the
    all_regulator_compare module which display distributions of rank response and DTO
    currently over all regulators/replicates in the database.

    :param rank_response_metadata: This is the result from a reactive.extended_task.
        Result can be retrieved with .result()
    :param bindingmanualqc_result: This is the result from a reactive.extended_task.
        Result can be retrieved with .result()
    :param logger: A logger object
    :return: None

    """

    # update the bindingmanualqc column options
    @reactive.effect
    def _():
        bindingmanualqc_local = bindingmanualqc_result.result()
        cols = list(bindingmanualqc_local.columns) + ["promotersetsig"]
        selected = list(input.bindingmanualqc_columns.get())

        ui.update_checkbox_group(
            "bindingmanualqc_columns", choices=cols, selected=selected
        )

    @reactive.calc
    def bindingmanualqc_display_table():
        selected_bindingmanualqc_cols = list(input.bindingmanualqc_columns.get())
        bindingmanualqc_metadata_local = bindingmanualqc_result.result()
        logger.debug(
            f"bindingmanualqc selected columns: {selected_bindingmanualqc_cols}"
        )

        return bindingmanualqc_metadata_local[selected_bindingmanualqc_cols]

    rank_response_distributions_server(
        "rank_response_distributions",
        rank_response_metadata=rank_response_metadata,
        logger=logger,
    )

    dto_distributions_server(
        "dto_distributions",
        rank_response_metadata=rank_response_metadata,
        logger=logger,
    )
