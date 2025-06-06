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
def binding_ui():
    # Get source choices for the sidebar
    binding_source_dict = get_source_name_dict("binding")

    source_selection_panel = create_accordion_panel(
        "Source Selection",
        ui.input_checkbox_group(
            "selected_sources",
            label="Select Binding Sources (0-3):",
            choices=binding_source_dict,
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
                    "matrix for TF binding datasets. The current binding datasets are: "
                ),
                ui.div(
                    ui.tags.p(
                        "This page includes binding data from multiple "
                        "experimental sources. Each technique provides genome-wide "
                        "measurements of transcription factor (TF) binding events, "
                        "but differs in resolution, noise profile, and protocol."
                    ),
                    ui.tags.ul(
                        ui.tags.li(
                            ui.tags.b("ChIP-chip: "),
                            "Chromatin immunoprecipitation followed by "
                            "microarray hybridization. This data is from the Young lab "
                            "and is publicly available at ",
                            ui.a(
                                "The Young Lab",
                                href="https://younglab.wi.mit.edu"
                                "/regulatory_code/GWLD.html",
                                target="_blank",
                            ),
                            ".",
                            ui.tags.br(),
                            ui.tags.small(
                                ui.em(
                                    "Harbison CT, Gordon DB, Lee TI, Rinaldi NJ, "
                                    "Macisaac KD, Danford TW, Hannett NM, Tagne JB, "
                                    "Reynolds DB, Yoo J, et al. 2004. Transcriptional "
                                    "regulatory code of a eukaryotic genome. "
                                    "Nature 431: 99–104.",
                                    ui.a(
                                        "doi:10.1038/nature02800",
                                        href="https://doi.org/10.1038/nature02800",
                                        target="_blank",
                                    ),
                                )
                            ),
                        ),
                        ui.tags.li(
                            ui.tags.b("ChIP-exo: "),
                            "Chromatin immunoprecipitation followed by exonuclease "
                            "digestion and sequencing. This protocol yields "
                            "high-resolution footprints of bound TFs with "
                            "base-pair precision and reduced background noise compared "
                            "to ChIP-chip or ChIP-seq. This dataset is produced by the "
                            "Pugh lab and is publicly available at ",
                            ui.a(
                                "yeastepigenome.org",
                                href="http://yeastepigenome.org",
                                target="_blank",
                            ),
                            ".",
                            ui.tags.br(),
                            ui.tags.small(
                                ui.em(
                                    "Rossi, Matthew J et al. 'A high-resolution "
                                    "protein architecture of the budding yeast genome.'"
                                    " Nature vol. 592,7853 (2021): 309–314. ",
                                    ui.a(
                                        "doi:10.1038/s41586-021-03314-8",
                                        href="https://doi.org/10.1038"
                                        "/s41586-021-03314-8",
                                        target="_blank",
                                    ),
                                )
                            ),
                        ),
                        ui.tags.li(
                            ui.tags.b("Calling Cards: "),
                            "An in vivo transposon-based TF method. ",
                            "A transposase is tagged to a TF of interest while an "
                            "enabling insertion events of a known transposon sequence "
                            "near TF binding sites. This data is produced in both the "
                            "Brent and Mitra labs at Washington University. "
                            "Most is not publicly available yet.",
                        ),
                    ),
                    ui.p(
                        "More information on how this data was parsed and "
                        "processed for the tfbindingandperturbation database can "
                        "be found ",
                        ui.a(
                            "here",
                            href="https://github.com/cmatKhan"
                            "/parsing_yeast_database_data",
                            target="_blank",
                        ),
                        ".",
                    ),
                ),
                id="binding-description",
            ),
            # Second row: Plot area container
            ui.div(
                # Left: Source Summary
                ui.div(
                    ui.card(
                        ui.card_header("Source Selection Summary"),
                        ui.card_body(
                            ui.div(
                                ui.output_ui("source_summary"),
                                id="binding-source-summary",
                            )
                        ),
                        ui.card_footer(
                            ui.p(
                                "Select binding sources from the sidebar to see "
                                "regulator counts and intersections.",
                                class_="text-muted",
                            ),
                        ),
                    ),
                    id="binding-source-container",
                ),
                # Right: Correlation matrix
                ui.div(
                    ui.card(
                        ui.card_header("Binding Correlation Matrix"),
                        ui.card_body(
                            ui.div(
                                correlation_matrix_ui("binding_corr_matrix"),
                                id="binding-corr-plot-wrapper",
                            ),
                            id="binding-corr-body",
                        ),
                        ui.card_footer(
                            ui.p(
                                "Click and drag to zoom in on a specific region of the "
                                "correlation matrix. Double click to reset the zoom.",
                                class_="text-muted",
                            ),
                        ),
                    ),
                    id="binding-corr-container",
                ),
                id="binding-plot-row",
            ),
            # Add styles at the bottom
            ui.tags.style(
                """
                #binding-description {
                    max-width: 100%;
                    margin-bottom: 1.5rem;
                }

                #binding-plot-row {
                    display: flex;
                    flex-direction: row;
                    justify-content: center;
                    align-items: flex-start;
                    gap: 2rem;
                }

                #binding-source-container {
                    flex: 1.2;
                    min-width: 0;
                    min-height: 500px;
                    display: flex;
                    flex-direction: column;
                    height: 100%;
                }

                #binding-corr-container {
                    flex: 0 0 500px;
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    height: 100%;
                }

                #binding-corr-plot-wrapper {
                    width: 450px;
                    height: 450px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                }

                #binding-corr-body {
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    flex: 1;
                }

                #binding-source-summary {
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
def binding_server(
    input: Inputs,
    output: Outputs,
    session: Session,
    *,
    binding_metadata_task: reactive.ExtendedTask,
    logger: Logger,
) -> reactive.calc:
    """
    This function produces the reactive/render functions necessary to producing the
    binding source selection summary and correlation matrix.

    :param binding_metadata_task: This is the result from a reactive.extended_task.
        Result can be retrieved with .result()
    :param logger: A logger object
    :return: A reactive.calc with the metadata filtered for the selected sources

    """

    # TODO: retrieving the predictors should be from the db as a reactive.extended_task
    tf_binding_df = pd.read_csv("tmp/shiny_data/cc_predictors_normalized.csv")
    tf_binding_df.set_index("target_symbol", inplace=True)
    correlation_matrix_server(
        "binding_corr_matrix",
        tf_binding_df=tf_binding_df,
        logger=logger,
    )

    # Initialize the source intersection calculator
    calculator = SourceIntersectionCalculator("binding", logger)

    @reactive.calc
    def selected_sources_metadata():
        """Get metadata filtered by selected sources."""
        selected = input.selected_sources.get()
        return calculator.get_filtered_metadata(binding_metadata_task, selected)

    @render.ui
    def source_summary():
        """Render the source selection summary using the calculator."""
        selected = input.selected_sources.get()

        logger.debug(f"binding_module: selected internal names from UI: {selected}")

        # Limit to maximum 3 selections
        if len(selected) > 3:
            ui.update_checkbox_group("selected_sources", selected=selected[:3])
            selected = selected[:3]

        if not selected:
            return ui.div(
                ui.h4("How to Use"),
                ui.p("Select 1-3 binding sources from the sidebar to see:"),
                ui.tags.ul(
                    ui.tags.li("Number of regulators in each selected source"),
                    ui.tags.li("Intersections between sources (when 2+ selected)"),
                    ui.tags.li("Three-way intersection (when 3 selected)"),
                ),
                style="text-align: center; margin-top: 50px;",
            )

        # Get the summary from the calculator
        try:
            summary = calculator.create_summary(binding_metadata_task, selected)
            logger.debug(f"binding_module: summary result: {summary}")
        except Exception as e:
            logger.error(f"binding_module: Error creating summary: {e}")
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
