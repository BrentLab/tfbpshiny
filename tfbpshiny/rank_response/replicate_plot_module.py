from logging import Logger

# %%
import plotly.graph_objects as go
from callingcardstools.Analysis.yeast.rank_response import compute_rank_response
from pandas.errors import EmptyDataError
from scipy.stats import binom
from shiny import Inputs, Outputs, Session, module, reactive, render, req, ui
from shinywidgets import output_widget, render_plotly
from tfbpapi import RankResponseAPI


# Function to calculate confidence interval for the random value
def binom_ci(trials, random_prob, alpha=0.05):
    lower_bound = binom.ppf(alpha / 2, trials, random_prob) / trials
    upper_bound = binom.ppf(1 - alpha / 2, trials, random_prob) / trials
    return lower_bound, upper_bound


def process_plot_data(key, data):
    """Process a single row of metadata to generate plot data."""
    subset_data = data[data["rank_bin"] <= 150]
    rr_summary = compute_rank_response(subset_data)

    plot_data = {
        "x": rr_summary["rank_bin"],
        "y": rr_summary["response_ratio"],
        "random_y": rr_summary["random"] if "random" in rr_summary else None,
        "ci": (
            rr_summary["rank_bin"].apply(lambda n: binom_ci(n, rr_summary["random"][0]))
            if "random" in rr_summary
            else None
        ),
    }

    return plot_data


def prepare_rank_response_data(rr_dict):
    """Prepare rank response data for plotting."""
    metadata = rr_dict.get("metadata")
    data_dict = rr_dict.get("data")

    # Use list comprehension to generate plots
    plots: dict = {}
    for _, row in metadata.iterrows():
        id = str(row["id"])
        data = data_dict.get(id)

        expression_id = str(row["expression"])
        promotersetsig_id = str(row["promotersetsig"])

        plots.setdefault(expression_id, {}).update(
            {promotersetsig_id: process_plot_data(promotersetsig_id, data)}
        )

    return plots


def add_traces_to_plot(fig, sample_id, add_random, **kwargs):
    """Add traces to a Plotly figure based on plot data."""
    # Add the main line for the promoterset signal
    fig.add_trace(
        go.Scatter(
            x=kwargs["x"],
            y=kwargs["y"],
            mode="lines",
            name=f"{sample_id}",
            legendrank=int(sample_id),
        )
    )

    if add_random:
        # Add the random line
        fig.add_trace(
            go.Scatter(
                x=kwargs["x"],
                y=kwargs["random_y"],
                mode="lines",
                name="Random",
                line=dict(dash="dash", color="black"),
                legendrank=0,
            )
        )

        if kwargs["ci"] is not None:
            ci_lower = kwargs["ci"].apply(lambda x: x[0])
            ci_upper = kwargs["ci"].apply(lambda x: x[1])

            # Add confidence interval lower bound
            fig.add_trace(
                go.Scatter(
                    x=kwargs["x"],
                    y=ci_lower,
                    mode="lines",
                    line=dict(width=0),
                    showlegend=False,
                )
            )

            # Add confidence interval upper bound and shade the area
            fig.add_trace(
                go.Scatter(
                    x=kwargs["x"],
                    y=ci_upper,
                    mode="lines",
                    fill="tonexty",
                    fillcolor="rgba(128, 128, 128, 0.3)",
                    line=dict(width=0),
                    showlegend=False,
                )
            )


def create_rank_response_replicate_plot(plots_dict):
    """Generate a dictionary of Plotly figures from the prepared rank response data."""
    output_dict = {}

    for expression_id, promotersetsig_dict in plots_dict.items():
        fig = go.Figure()
        add_random = True
        for promotersetsig_id, plot_data in promotersetsig_dict.items():
            # Use the helper function to add traces to the plot
            add_traces_to_plot(fig, promotersetsig_id, add_random, **plot_data)
            add_random = False  # Add random line only once

        # Update the layout of the figure
        fig.update_layout(
            title={
                "text": f"Rank Response for Expression ID {expression_id}",
                "x": 0.5,
            },
            yaxis_title="# Responsive / # Genes",
            xaxis_title="Number of Genes, Ranked by Binding Score",
            xaxis=dict(tick0=0, dtick=5, range=[0, 150]),  # Set x-axis ticks and range
            yaxis=dict(
                tick0=0, dtick=0.1, range=[0, 1.0]
            ),  # Set y-axis ticks and range
        )

        output_dict[expression_id] = fig

    return output_dict


# ## Example

# %%
# Set up the environment
# import dotenv

# from tfbpapi import *

# dotenv.load_dotenv("/home/chase/code/tfbpshiny/.env", override=True)

# # configure the logger to print to console
# import logging

# logging.basicConfig(level=logging.DEBUG)

# rr_api = RankResponseAPI()

# # %%
# rr_api.pop_params()
# rr_api.push_params(
#     {
#         "regulator_symbol": "OAF1",
#         "expression_conditions": "expression_source=mcisaac_oe,time=15"
#     }
# )

# rr_dict = await rr_api.read(retrieve_files=True)

# # %%
# plots = prepare_rank_response_data(rr_dict)

# # %%
# x = create_rank_response_replicate_plot(plots)

# %%
# to show data, do x.get(<id>).show()

# %%


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
    logger: Logger,
):

    rr_metadata = reactive.Value()

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

        plot_dict_by_source = {}
        promotersetsig_set = set()
        for source in expression_sources:
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
                ui.h3(f"Expression Source: {source}"),
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
                # promotersetsig_selected = _promotersetsig_selected.get()
                for trace in fig["data"]:
                    trace["visible"] = True
                    # NOTE: this was here b/c I wanted there to be a way to
                    # select which traces to show based on other reactives, ie
                    # promotersetsig_selected. But, adding it means that the
                    # CI aren't shown for some reason
                    # (
                    #     "legendonly"
                    #     if trace["name"] not in promotersetsig_selected
                    #     else True
                    # )

                @output(id=plot_id)
                @render_plotly
                def render_plot(fig=fig):
                    return fig

        logger.info("Rank response plots rendered successfully.")

    return rr_metadata
