from logging import Logger

import pandas as pd
from shiny import Inputs, Outputs, Session, module, reactive, render, ui

from ..misc.correlation_plot_module import (
    correlation_matrix_server,
    correlation_matrix_ui,
)
from ..misc.source_intersection_calculator import SourceIntersectionCalculator
from ..utils.create_accordion_panel import create_accordion_panel
from ..utils.source_name_lookup import get_source_name_dict


@module.ui
def perturbation_response_ui():
    # Get source choices for the sidebar
    perturbation_source_dict = get_source_name_dict("perturbation_response")

    source_selection_panel = create_accordion_panel(
        "Source Selection",
        ui.input_checkbox_group(
            "selected_sources",
            label="Select Perturbation Response Sources (0-3):",
            choices=perturbation_source_dict,
            selected=[],
        ),
    )

    return ui.layout_sidebar(
        ui.sidebar(
            ui.accordion(
                source_selection_panel,
                id=module.resolve_id("source_accordion"),
                open=None,
                multiple=True,
            ),
            width="300px",
        ),
        ui.div(
            # First row: Description
            ui.div(
                ui.p(
                    "This page displays the source selection summary and correlation "
                    "matrix for TF perturbation response datasets. The current "
                    "datasets include data derived from gene deletions and "
                    "overexpression methods."
                ),
                ui.div(
                    ui.tags.p(
                        "Each dataset captures the effect on gene expression of "
                        "perturbing a regulator These experimental approaches differ "
                        "in their perturbation strategy and noise profiles."
                    ),
                    ui.tags.ul(
                        ui.tags.li(
                            ui.tags.b("Overexpression: "),
                            "This data is from the McIsaac lab. "
                            "The TF is overexpressed from a strong promoter via "
                            "estradiol induction of an artificial TF. Gene expression "
                            "is measured via microarray at various time points. We are "
                            "currently displaying results for the 15 minute "
                            "time point. The data is publicly available from: ",
                            ui.a(
                                "Calico labs",
                                href="https://idea.research.calicolabs.com/data",
                                target="_blank",
                            ),
                            ".",
                            ui.tags.br(),
                            ui.tags.small(
                                ui.em(
                                    "Hackett, Sean R et al. 'Learning causal networks "
                                    "using inducible transcription factors and "
                                    "transcriptome-wide time series.' "
                                    "Molecular systems biology vol. 16,3 (2020): "
                                    "e9174. ",
                                    ui.a(
                                        "doi:10.15252/msb.20199174",
                                        href="https://doi.org/10.15252/msb.20199174",
                                        target="_blank",
                                    ),
                                )
                            ),
                        ),
                        ui.tags.li(
                            ui.tags.b("2014 Transcription Factor Knock Out (TFKO): "),
                            "Deletion of a transcription factor's coding region. "
                            "Gene expression is measured via microarray. The data is "
                            "publicly available from the ",
                            ui.a(
                                "Holstege Lab.",
                                href="https://idea.research.calicolabs.com/data",
                                target="_blank",
                            ),
                            ".",
                            ui.tags.br(),
                            ui.tags.small(
                                ui.em(
                                    "Kemmeren P, Sameith K, van de Pasch LA, "
                                    "Benschop JJ, Lenstra TL, Margaritis T, "
                                    "O'Duibhir E, Apweiler E, van Wageningen S, "
                                    "Ko CW, et al. 2014. Large-scale genetic "
                                    "perturbations reveal regulatory networks and an "
                                    "abundance of gene-specific repressors. Cell 157: "
                                    "740–752.",
                                    ui.a(
                                        "doi:10.1016/j.cell.2014.02.054",
                                        href="https://doi.org/10.1016"
                                        "/j.cell.2014.02.054",
                                        target="_blank",
                                    ),
                                )
                            ),
                        ),
                        ui.tags.li(
                            ui.tags.b("2007 TFKO: "),
                            "This is also a deletion data set, with gene expression "
                            "measured via microarray. This is a re-analysis of data "
                            "produced in the Hu lab. The data is provided in the "
                            "Supplement of the following paper: ",
                            ui.tags.br(),
                            ui.tags.small(
                                ui.em(
                                    "Reimand, Jüri et al. 'Comprehensive reanalysis of "
                                    "transcription factor knockout expression data in "
                                    "Saccharomyces cerevisiae reveals many new "
                                    "targets.' Nucleic acids research vol. 38,14 "
                                    "(2010): 4768-77. ",
                                    ui.a(
                                        "doi:10.1093/nar/gkq232",
                                        href="https://doi.org/10.1093/nar/gkq232",
                                        target="_blank",
                                    ),
                                )
                            ),
                        ),
                    ),
                    ui.p(
                        "More information on how this data was parsed and "
                        "processed for the tfbindingandperturbation database can be "
                        "found ",
                        ui.a(
                            "here",
                            href="https://github.com/cmatKhan"
                            "/parsing_yeast_database_data",
                            target="_blank",
                        ),
                        ".",
                    ),
                ),
                id="perturbation-description",
            ),
            # Second row: Plot area container
            ui.div(
                # Left: Source Summary
                ui.div(
                    ui.card(
                        ui.card_header(
                            "Perturbation Response Source Selection Summary"
                        ),
                        ui.card_body(
                            ui.div(
                                ui.output_ui("source_summary"),
                                id="perturbation-source-summary",
                            )
                        ),
                        ui.card_footer(
                            ui.p(
                                "Select perturbation response sources from the sidebar "
                                "to see regulator counts and intersections.",
                                class_="text-muted",
                            ),
                        ),
                    ),
                    id="perturbation-source-container",
                ),
                # Right: Correlation matrix
                ui.div(
                    ui.card(
                        ui.card_header("Perturbation Response Correlation Matrix"),
                        ui.card_body(
                            ui.div(
                                correlation_matrix_ui("perturbation_corr_matrix"),
                                id="perturbation-corr-plot-wrapper",
                            ),
                            id="perturbation-corr-body",
                        ),
                        ui.card_footer(
                            ui.p(
                                "Click and drag to zoom in on a specific region of "
                                "the correlation matrix. Double click to reset the "
                                "zoom.",
                                class_="text-muted",
                            ),
                        ),
                    ),
                    id="perturbation-corr-container",
                ),
                id="perturbation-plot-row",
            ),
            # Add styles at the bottom
            ui.tags.style(
                """
                #perturbation-description {
                    max-width: 100%;
                    margin-bottom: 1.5rem;
                }

                #perturbation-plot-row {
                    display: flex;
                    flex-direction: row;
                    justify-content: center;
                    align-items: flex-start;
                    gap: 2rem;
                }

                #perturbation-source-container {
                    flex: 1.2;
                    min-width: 0;
                    min-height: 500px;
                    display: flex;
                    flex-direction: column;
                    height: 100%;
                }

                #perturbation-corr-container {
                    flex: 0 0 500px;
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    height: 100%;
                }

                #perturbation-corr-plot-wrapper {
                    width: 450px;
                    height: 450px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                }

                #perturbation-corr-body {
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    flex: 1;
                }

                #perturbation-source-summary {
                    padding: 20px;
                    min-height: 400px;
                }

                .card {
                    display: flex;
                    flex-direction: column;
                    height: 100%;
                }

                .card-body {
                    flex: 1;
                }

                .card-footer {
                    margin-top: auto;
                }
                """
            ),
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
    """
    This function produces the reactive/render functions necessary to producing the
    perturbation response source selection summary and correlation matrix for the
    perturbation response data.

    :param pr_metadata_task: This is the result from a reactive.extended_task. Result
        can be retrieved with .result()
    :param logger: A logger object
    :return: A reactive.calc with the metadata filtered for the selected sources

    """

    # TODO: retrieving the response should be from the db as a reactive.extended_task
    tf_pr_df = pd.read_csv("tmp/shiny_data/response_data.csv")
    tf_pr_df.set_index("target_symbol", inplace=True)
    correlation_matrix_server(
        "perturbation_corr_matrix",
        tf_binding_df=tf_pr_df,
        logger=logger,
    )

    # Initialize the source intersection calculator
    calculator = SourceIntersectionCalculator("perturbation_response", logger)

    @reactive.calc
    def selected_sources_metadata():
        """Get metadata filtered by selected sources."""
        selected = input.selected_sources.get()
        return calculator.get_filtered_metadata(pr_metadata_task, selected)

    @render.ui
    def source_summary():
        """Render the source selection summary using the calculator."""
        selected = input.selected_sources.get()

        logger.debug(
            f"perturbation_response_module: selected internal names from UI: {selected}"
        )

        # Limit to maximum 3 selections
        if len(selected) > 3:
            ui.update_checkbox_group("selected_sources", selected=selected[:3])
            selected = selected[:3]

        if not selected:
            return ui.div(
                ui.h4("How to Use"),
                ui.p(
                    "Select 1-3 perturbation response sources from the sidebar to see:"
                ),
                ui.tags.ul(
                    ui.tags.li("Number of regulators in each selected source"),
                    ui.tags.li("Intersections between sources (when 2+ selected)"),
                    ui.tags.li("Three-way intersection (when 3 selected)"),
                ),
                style="text-align: center; margin-top: 50px;",
            )

        # Get the summary from the calculator
        try:
            summary = calculator.create_summary(pr_metadata_task, selected)
            logger.debug(f"perturbation_response_module: summary result: {summary}")
        except Exception as e:
            logger.error(f"perturbation_response_module: Error creating summary: {e}")
            return ui.div(
                ui.h4("Error"),
                ui.p(f"An error occurred: {str(e)}"),
                style="text-align: center; margin-top: 50px;",
            )

        if summary["type"] == "empty":
            return ui.div(
                ui.h4("No Data Available"),
                ui.p("No regulators found for the selected sources."),
                style="text-align: center; margin-top: 50px;",
            )

        elif summary["type"] == "single":
            return ui.div(
                ui.h4(f"Selected Source: {summary['source']}"),
                ui.p(f"Number of regulators: {summary['count']}"),
                style="text-align: center; margin-top: 50px;",
            )

        elif summary["type"] == "double":
            source1, source2 = summary["sources"]
            count1, count2 = summary["counts"]
            intersection = summary["intersection"]

            return ui.div(
                ui.h4("Two Sources Selected"),
                ui.div(
                    ui.p(f"{source1}: {count1} regulators"),
                    ui.p(f"{source2}: {count2} regulators"),
                    ui.p(f"Intersection: {intersection} regulators"),
                    style="margin-top: 30px;",
                ),
            )

        elif summary["type"] == "triple":
            source1, source2, source3 = summary["sources"]
            count1, count2, count3 = summary["counts"]
            int_12, int_13, int_23 = summary["pairwise_intersections"]
            int_123 = summary["triple_intersection"]

            return ui.div(
                ui.h4("Three Sources Selected"),
                ui.div(
                    ui.h5("Individual Sources:"),
                    ui.p(f"{source1}: {count1} regulators"),
                    ui.p(f"{source2}: {count2} regulators"),
                    ui.p(f"{source3}: {count3} regulators"),
                    ui.h5("Pairwise Intersections:"),
                    ui.p(f"{source1} ∩ {source2}: {int_12} regulators"),
                    ui.p(f"{source1} ∩ {source3}: {int_13} regulators"),
                    ui.p(f"{source2} ∩ {source3}: {int_23} regulators"),
                    ui.h5("Three-way Intersection:"),
                    ui.p(f"{source1} ∩ {source2} ∩ {source3}: {int_123} regulators"),
                    style="margin-top: 20px;",
                ),
            )

        return ui.div(
            ui.p("Unexpected summary type."),
            style="text-align: center; margin-top: 50px;",
        )

    return selected_sources_metadata
