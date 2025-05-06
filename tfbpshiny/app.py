import logging
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from shiny import App, reactive, run_app, ui
from tfbpapi import (
    BindingAPI,
    BindingManualQCAPI,
    ExpressionAPI,
    PromoterSetSigAPI,
    RankResponseAPI,
)

from .binding_perturbation_upset_module import upset_plot_server, upset_plot_ui
from .compare_module import compare_server, compare_ui
from .correlation_plot_module import correlation_matrix_server, correlation_matrix_ui
from .utils import make_metadata_task

# Only load .env if not running in production
if not os.getenv("DOCKER_ENV"):
    load_dotenv(dotenv_path=Path(".env"))

logger = logging.getLogger("shiny")
logger.setLevel(logging.DEBUG)  # Set the logging level for the "shiny" logger

# Prevent propagation to the root logger
logger.propagate = False

# Check if the logger already has handlers
if not logger.handlers:
    # Create a StreamHandler
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.DEBUG)  # Set the handler's logging level

    # Define the log format
    formatter = logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    stream_handler.setFormatter(formatter)

    # Add the handler to the "shiny" logger
    logger.addHandler(stream_handler)

# All regulators / individual regulators rather than "comparison" in top level tabs

app_ui = ui.page_fillable(
    ui.panel_title("Yeast Regulatory DB", window_title="Yeast Regulatory DB"),
    ui.include_css((Path(__file__).parent / "style.css").resolve()),
    ui.navset_card_pill(
        ui.nav_panel(
            "Binding",
            ui.layout_columns(
                upset_plot_ui("binding_upset"),
                ui.card(ui.output_table("binding_set_subset_table")),
                correlation_matrix_ui("binding_corr_matrix"),
                col_widths={"sm": (12, 6, 6)},
            ),
            value="binding_tab",
        ),
        ui.nav_panel(
            "Perturbation Response",
            ui.layout_columns(
                upset_plot_ui("perturbation_response_upset"),
                ui.card(ui.output_table("perturbation_set_subset_table")),
                correlation_matrix_ui("perturbation_corr_matrix"),
                col_widths={"sm": (12, 6, 6)},
            ),
            value="perturbation_response_tab",
        ),
        ui.nav_panel(
            "All Regulator Comparisons",
            compare_ui("compare_all"),
            value="all_compare_tab",
        ),
        ui.nav_panel(
            "Individual Regulator Comparisons",
            compare_ui("compare_individual"),
            value="individual_compare_tab",
        ),
        id="tab",
    ),
)


def app_server(input, output, session):

    binding_api = BindingAPI()
    bindingmanualq_api = BindingManualQCAPI()
    expression_api = ExpressionAPI()
    promotersetsig_api = PromoterSetSigAPI()
    rank_response_api = RankResponseAPI()

    get_binding_metadata = make_metadata_task(binding_api, "binding", logger)
    get_perturbation_response_metadata = make_metadata_task(
        expression_api, "perturbation_response", logger
    )
    get_rank_response_metadata = make_metadata_task(
        rank_response_api, "rank_response", logger
    )

    get_promotersetsig_metadata = make_metadata_task(
        promotersetsig_api, "promotersetsig", logger
    )

    get_bindingmanualqc_metadata = make_metadata_task(
        bindingmanualq_api, "bindingmanualqc", logger
    )

    selected_sets = {}

    source_name_dict = {
        "binding": {
            "harbison_chip": "2004 ChIP-chip",
            "chipexo_pugh_allevents": "2021 ChIP-exo",
            "brent_nf_cc": "Calling Cards",
        },
        "perturbation_response": {
            "mcisaac_oe": "mcisaac_oe",
            "kemmeren_tfko": "kemmeren_tfko",
            "hu_reimann_tfko": "hu_reimann_tfko",
        },
    }

    # this provides a location to execute on_start operations
    initial_run = reactive.Value(True)

    @reactive.effect()
    def _():
        with reactive.isolate():
            if initial_run.get():
                logger.info("Executing on_start logic")
                get_binding_metadata()
                get_perturbation_response_metadata()
                get_rank_response_metadata()
                get_promotersetsig_metadata()
                get_bindingmanualqc_metadata()
                initial_run.set(False)

    selected_sets["binding"] = upset_plot_server(
        "binding_upset",
        metadata_result=get_binding_metadata,
        source_name_dict=source_name_dict.get("binding"),
        logger=logger,
    )

    # TODO: make this a reactive.extended_task
    tf_binding_df = pd.read_csv("tmp/shiny_data/cc_predictors_normalized.csv")
    tf_binding_df.set_index("target_symbol", inplace=True)
    correlation_matrix_server(
        "binding_corr_matrix",
        tf_binding_df=tf_binding_df,
        logger=logger,
    )

    # TODO: make this a reactive.extended_task
    tf_pr_df = pd.read_csv("tmp/shiny_data/response_data.csv")
    tf_pr_df.set_index("target_symbol", inplace=True)
    correlation_matrix_server(
        "perturbation_corr_matrix",
        tf_binding_df=tf_pr_df,
        logger=logger,
    )

    selected_sets["perturbation_response"] = upset_plot_server(
        "perturbation_response_upset",
        metadata_result=get_perturbation_response_metadata,
        source_name_dict=source_name_dict.get("perturbation_response"),
        logger=logger,
    )

    compare_server(
        "compare",
        rank_response_metadata=get_rank_response_metadata,
        bindingmanualqc_result=get_bindingmanualqc_metadata,
        logger=logger,
    )


# Create an app instance
app = App(ui=app_ui, server=app_server)

if __name__ == "__main__":
    run_app(
        "tfbpshiny.app:app", reload=True, reload_dirs=["."], port=8010
    )  # type: ignore
