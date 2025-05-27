"""
This module contains the server and UI components for the rank response replicate plots.

It is both complicated and ugly. It does have a commented out portion that allows you to
call the functions to create the plots interactively in vscode ( not the # %% which
creates cells in the .py file).

"""

from logging import Logger

from pandas.errors import EmptyDataError
from shiny import Inputs, Outputs, Session, module, reactive, render, req, ui
from shinywidgets import output_widget, render_plotly
from tfbpapi import RankResponseAPI

from ..utils.plot_formatter import plot_formatter
from ..utils.rank_response_replicate_plot_utils import (
    create_rank_response_replicate_plot,
    prepare_rank_response_data,
)
from ..utils.source_name_lookup import get_source_name_dict


@module.ui
def rank_response_replicate_plot_ui():
    return ui.output_ui("dynamic_expression_containers")


@module.server
def rank_response_replicate_plot_server(
    input: Inputs,
    output: Outputs,
    session: Session,
    *,
    selected_regulator: reactive.value,
    selected_promotersetsigs: reactive.value,
    logger: Logger,
):
    """
    This function produces the reactive/render functions necessary to producing the rank
    response replicate plots. All arguments must be passed as keyword arguments.

    Unlike most of the other modules, this does hit the database. It is an ExtendedTask
    request and can be quite log if there are many replicates.

    :param selected_regulator: A reactive value that contains the selected regulator
    :param logger: A logger object
    :return: A reactive value that contains the rank response metadata

    """
    perturbation_source_dict = get_source_name_dict(datatype="perturbation_response")

    rr_metadata = reactive.Value()  # type: ignore

    # Fetch data asynchronously -- see the main app for documentation on this pattern
    # of async fetching
    @reactive.extended_task
    async def fetch_data(regulator):
        with ui.Progress(min=0, max=1) as p:
            p.set(
                0.5,
                message="Pulling RankResponse data",
                detail="This may take a while...",
            )
            rank_response_api = RankResponseAPI(
                params={
                    "regulator_id": regulator,
                    "expression_conditions": (
                        "expression_source=kemmeren_tfko;"
                        "expression_source=mcisaac_oe,time=15"
                    ),
                }
            )
            logger.info(
                "Fetching data from RankResponseAPI with params: "
                f"{rank_response_api.params}"
            )
            try:
                result = await rank_response_api.read(retrieve_files=True)
            except EmptyDataError as exc:
                logger.error(f"Failed to fetch data for regulator {regulator}: {exc}")
                result = {}
            return result

    @reactive.effect
    def _():
        req(selected_regulator)
        selected_regulator_local = selected_regulator.get()
        if selected_regulator_local:
            logger.info(
                f"Selected regulator for rank response "
                f"plots: {selected_regulator_local}"
            )
            fetch_data(selected_regulator_local)

    # Process fetched data into plot dictionary
    @reactive.calc
    def update_plot_dict():
        rr_dict = fetch_data.result()
        if not rr_dict:
            logger.warning("No data retrieved for plots.")
            return {}

        metadata = rr_dict.get("metadata")
        rr_metadata.set(metadata)
        expression_sources = metadata["expression_source"].unique()
        # Sort the expression sources alphabetically for consistent plot order
        sorted_expression_sources = sorted(list(expression_sources))
        logger.info(
            "Derived and sorted expression_sources order: %s",
            list(sorted_expression_sources),
        )

        plot_dict_by_source = {}
        promotersetsig_set = set()
        for source in sorted_expression_sources:  # Iterate over the sorted list
            filtered_metadata = metadata[metadata["expression_source"] == source]
            try:
                promotersetsig_set.update(
                    [str(x) for x in filtered_metadata.promotersetsig.unique().tolist()]
                )
            except AttributeError:
                logger.warning(
                    f"Expression source {source} has no promotersetsig data."
                )
            plot_dict_by_source[source] = prepare_rank_response_data(
                {"metadata": filtered_metadata, "data": rr_dict.get("data")}
            )

        # add random to the list so that it is initially visible
        promotersetsig_set.add("Random")

        return plot_dict_by_source

    # Prepare dynamic UI
    @reactive.Calc
    def prepare_dynamic_ui():
        plots_by_source = update_plot_dict()
        if not plots_by_source:
            return []

        containers: dict = {}
        for source, plots_dict in plots_by_source.items():
            container = ui.card(
                ui.h3(f"Expression Source: {perturbation_source_dict[source]}"),
                *[
                    output_widget(f"plot_{source}_{expression_id}")
                    for expression_id in plots_dict.keys()
                ],
            )
            containers.setdefault(source, []).append(container)

        logger.info("Dynamic UI prepared.")
        return containers

    # Render dynamic UI
    @output
    @render.ui
    def dynamic_expression_containers():
        containers = prepare_dynamic_ui()
        if not containers:
            return ui.p("No data available.")

        # Ensure each card is correctly wrapped in a column
        ui_element = ui.row(
            *[
                ui.column(
                    6, card
                )  # Ensure the width is valid and card is correctly passed
                for container in containers.values()
                for card in container  # Flatten containers to individual cards
            ]
        )
        return ui_element

    # Render plots dynamically
    @reactive.effect()
    # @reactive.event(_plot_dict_by_source)
    def _():
        # plots_by_source = _plot_dict_by_source.get()
        plots_by_source = update_plot_dict()
        if not plots_by_source:
            logger.warning("No rank response replicate plots to render.")
            return

        for source, plots_dict in plots_by_source.items():
            for expression_id, fig in create_rank_response_replicate_plot(
                plots_dict
            ).items():
                plot_id = f"plot_{source}_{expression_id}"
                # see note below
                selected_promotersetsig_local = selected_promotersetsigs.get()
                if selected_promotersetsig_local:
                    if selected_promotersetsig_local:
                        for trace in fig["data"]:
                            logger.error(
                                "trace[trace[name] in selected_promotersetsig: %s",
                                trace["name"],
                            )
                            trace["visible"] = (
                                True
                                if trace["name"] in selected_promotersetsig_local
                                else "legendonly"
                            )

                @output(id=plot_id)
                @render_plotly
                def render_plot(fig=fig):
                    return plot_formatter(fig)

        logger.info("Rank response plots rendered successfully.")

    return rr_metadata
