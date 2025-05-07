import logging
import os
import time
from pathlib import Path
from typing import Literal, cast

from dotenv import load_dotenv
from shiny import App, reactive, ui
from tfbpapi import (
    BindingAPI,
    BindingManualQCAPI,
    ExpressionAPI,
    PromoterSetSigAPI,
    RankResponseAPI,
)

from configure_logger import configure_logger

from .tabs.all_regulator_compare_module import (
    all_regulator_compare_server,
    all_regulator_compare_ui,
)
from .tabs.binding_module import binding_server, binding_ui
from .tabs.home_module import home_ui
from .tabs.individual_regulator_compare_module import (
    individual_regulator_compare_server,
    individual_regulator_compare_ui,
)
from .tabs.perturbation_response_module import (
    perturbation_response_server,
    perturbation_response_ui,
)
from .utils.get_metadata_task import get_metadata_task

# Only load .env if not running in production
if not os.getenv("DOCKER_ENV"):
    load_dotenv(dotenv_path=Path(".env"))

logger = logging.getLogger("shiny")


log_file = f"tfbpshiny_{time.strftime('%Y%m%d-%H%M%S')}.log"
log_level = int(os.getenv("TFBPSHINY_LOG_LEVEL", "10"))
handler_type = cast(
    Literal["console", "file"], os.getenv("TFBPSHINY_LOG_HANDLER", "console")
)
configure_logger(
    "shiny",
    level=log_level,
    handler_type=handler_type,
    log_file=log_file,
)


# All regulators / individual regulators rather than "comparison" in top level tabs

app_ui = ui.page_fillable(
    ui.panel_title(
        "TF Binding and Perturbation", window_title="TF Binding and Perturbation"
    ),
    ui.include_css((Path(__file__).parent / "style.css").resolve()),
    ui.navset_card_pill(
        ui.nav_panel(
            "Home",
            home_ui("home_tab_ui"),
            value="home_tab",
        ),
        ui.nav_panel(
            "Binding",
            binding_ui("binding_tab_ui"),
            value="binding_tab",
        ),
        ui.nav_panel(
            "Perturbation Response",
            perturbation_response_ui("perturbation_response_tab_ui"),
            value="perturbation_response_tab",
        ),
        ui.nav_panel(
            "All Regulator Comparisons",
            all_regulator_compare_ui("compare_all"),
            value="all_compare_tab",
        ),
        ui.nav_panel(
            "Individual Regulator Comparisons",
            individual_regulator_compare_ui("compare_individual"),
            value="individual_compare_tab",
        ),
        id="tab",
    ),
)


def app_server(input, output, session):

    # ---- Instantiate API class instances and other static variables ----

    # set up the API class instances
    binding_api = BindingAPI()
    bindingmanualq_api = BindingManualQCAPI()
    expression_api = ExpressionAPI()
    promotersetsig_api = PromoterSetSigAPI()
    rank_response_api = RankResponseAPI()

    # ---- Instantiate reactives, and objects that store reactives ----

    # this reactive is used to execute the "init" function once when the app starts.
    # it is set to False after the first run and not used again
    initial_run = reactive.Value(True)

    # ---- functions to get the metadata for the API class instances ----

    get_binding_metadata = get_metadata_task(binding_api, "binding", logger)
    get_perturbation_response_metadata = get_metadata_task(
        expression_api, "perturbation_response", logger
    )
    get_rank_response_metadata = get_metadata_task(
        rank_response_api, "rank_response", logger
    )

    get_promotersetsig_metadata = get_metadata_task(
        promotersetsig_api, "promotersetsig", logger
    )

    get_bindingmanualqc_metadata = get_metadata_task(
        bindingmanualq_api, "bindingmanualqc", logger
    )

    # ---- Main server logic ----

    # This is the "init" function and runs once when the app starts
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

    _ = binding_server(
        "binding_tab_ui",
        binding_metadata_task=get_binding_metadata,
        logger=logger,
    )

    _ = perturbation_response_server(
        "perturbation_response_tab_ui",
        pr_metadata_task=get_perturbation_response_metadata,
        logger=logger,
    )

    all_regulator_compare_server(
        "compare_all",
        rank_response_metadata=get_rank_response_metadata,
        bindingmanualqc_result=get_bindingmanualqc_metadata,
        logger=logger,
    )

    individual_regulator_compare_server(
        "compare_individual",
        rank_response_metadata=get_rank_response_metadata,
        bindingmanualqc_result=get_bindingmanualqc_metadata,
        logger=logger,
    )


# Create an app instance
app = App(ui=app_ui, server=app_server)
