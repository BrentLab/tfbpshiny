from logging import Logger

from shiny import Inputs, Outputs, Session, module, reactive, ui

from ..misc.dto_distributions_module import (
    dto_distributions_server,
    dto_distributions_ui,
)
from ..misc.univariate_pvalue_distributions_module import (
    univariate_pvalue_distributions_server,
    univariate_pvalue_distributions_ui,
)
from ..rank_response.distributions_module import (
    rank_response_distributions_server,
    rank_response_distributions_ui,
)
from ..utils.rename_dataframe_data_sources import get_source_name_dict

# these are used in the UI to set choices for the binding and perturbation response
# choices. The display is the display name, the value is the data source level
# in the database metadata
binding_data_source_lookup = get_source_name_dict("binding")
perturbation_response_source_lookup = get_source_name_dict("perturbation_response")


@module.ui
def all_regulator_compare_ui():
    return ui.layout_sidebar(
        ui.sidebar(
            ui.input_checkbox_group(
                "binding_data_sources",
                label="Binding Data Sources",
                choices=binding_data_source_lookup,
            ),
            ui.input_checkbox_group(
                "perturbation_response_data_sources",
                label="Perturbation Response Data Sources",
                choices=perturbation_response_source_lookup,
            ),
            ui.input_switch(
                "only_shared_regulators",
                label="Only Show Shared Regulators",
                value=True,
            ),
        ),
        ui.row(
            ui.div(
                ui.tags.p(
                    "This page displays distribution plots for Rank Response, "
                    "Dual Threshold Optimization (DTO) empirical p-value, "
                    "and Univariate p-value. "
                    "Use the sidebar to select binding and perturbation "
                    "response data sources, "
                    "and optionally restrict the view to regulators shared "
                    "across all selected datasets."
                ),
                ui.tags.ul(
                    ui.tags.li(
                        ui.tags.b("Rank Response: "),
                        "Target genes are ranked by binding strength, and "
                        "perturbation response is binarized into "
                        "response/non-response. ",
                        "The distribution shows the proportion of genes labeled "
                        "as responsive among the top 25 most strongly bound. ",
                        "See the original method described in ",
                        ui.a(
                            "Kang et al., 2020",
                            href="https://genome.cshlp.org/content/30/3/459",
                            target="_blank",
                        ),
                        ".",
                    ),
                    ui.tags.li(
                        ui.tags.b("DTO empirical p-value: "),
                        "DTO compares two ranked "
                        "lists—typically binding and response—to find "
                        "thresholds that minimize ",
                        "the hypergeometric p-value of their overlap. The empirical "
                        "p-value reflects the rank overlap's extremity "
                        "relative to a null distribution generated via permutation.",
                    ),
                    ui.tags.li(
                        ui.tags.b("Univariate p-value: "),
                        "The p-value from an ordinary least squares (OLS) "
                        "regression model that predicts perturbation response "
                        "based on the binding score of a regulator.",
                    ),
                ),
            )
        ),
        ui.navset_tab(
            ui.nav_panel(
                "Rank Response",
                ui.div(
                    rank_response_distributions_ui("rank_response_distributions"),
                    class_="plotly-graph-responsive",
                    style="width: 100%; min-height: 450px; height: auto;",
                ),
            ),
            ui.nav_panel(
                "DTO",
                ui.div(
                    dto_distributions_ui("dto_distributions"),
                    class_="plotly-graph-responsive",
                    style="width: 100%; min-height: 450px; height: auto;",
                ),
            ),
            ui.nav_panel(
                "Univariate P-value",
                ui.div(
                    univariate_pvalue_distributions_ui(
                        "univariate_pvalue_distributions"
                    ),
                    class_="plotly-graph-responsive",
                    style="width: 100%; min-height: 450px; height: auto;",
                ),
            ),
            id="distribution_tabs",
            selected="Rank Response",
        ),
        # Add custom CSS for plotly responsiveness
        ui.tags.style(
            """
            .plotly-graph-responsive {
                width: 100%;
                height: auto;
                overflow: visible;
            }
            .plotly-graph-responsive > div {
                width: 100% !important;
                height: auto !important;
                min-height: 450px;
            }
        """
        ),
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

    @reactive.calc
    def filtered_rr_metadata():
        """
        This function filters the rank response metadata based on the selected data
        sources and returns the filtered DataFrame.

        :return: A filtered DataFrame based on the selected data sources

        """
        rr_local = rank_response_metadata.result()
        # Get the selected data sources from the input
        binding_data_sources = input.binding_data_sources.get()
        perturbation_response_data_sources = (
            input.perturbation_response_data_sources.get()
        )
        only_shared_regulators = input.only_shared_regulators.get()

        logger.info(
            "binding_data_sources: %s, perturbation_response_data_sources: %s",
            binding_data_sources,
            perturbation_response_data_sources,
        )

        fltr_df = rr_local.query(
            "binding_source in @binding_data_sources and "
            "expression_source in @perturbation_response_data_sources"
        )

        if only_shared_regulators:
            regulator_sets = fltr_df.groupby(["binding_source", "expression_source"])[
                "regulator_symbol"
            ].apply(set)

            if not regulator_sets.empty:
                # get the intersection of all sets
                shared_regulators = set.intersection(*regulator_sets)
                # retain only the rows with the shared regulators
                fltr_df = fltr_df[fltr_df["regulator_symbol"].isin(shared_regulators)]
                logger.info(
                    "Filtered to only shared regulators. "
                    "Resulting rows: {len(fltr_df)}"
                )
            else:
                # No valid data, return empty DataFrame with same structure
                fltr_df = fltr_df.iloc[0:0]

        # Filter the rank response metadata based on the selected data sources
        return fltr_df

    # update the bindingmanualqc column options
    @reactive.effect
    def _():
        bindingmanualqc_local = bindingmanualqc_result.result()
        cols = list(bindingmanualqc_local.columns) + ["promotersetsig"]
        selected = list(input.bindingmanualqc_columns.get())

        ui.update_checkbox_group(
            "bindingmanualqc_columns", choices=cols, selected=selected
        )

    rank_response_distributions_server(
        "rank_response_distributions",
        rank_response_metadata=filtered_rr_metadata,
        logger=logger,
    )

    dto_distributions_server(
        "dto_distributions",
        rank_response_metadata=filtered_rr_metadata,
        logger=logger,
    )

    univariate_pvalue_distributions_server(
        "univariate_pvalue_distributions",
        rank_response_metadata=filtered_rr_metadata,
        logger=logger,
    )
