from logging import Logger

import pandas as pd
from shiny import Inputs, Outputs, Session, module, reactive, ui

from ..misc.binding_perturbation_upset_module import upset_plot_server, upset_plot_ui
from ..misc.correlation_plot_module import (
    correlation_matrix_server,
    correlation_matrix_ui,
)
from ..utils.source_name_lookup import get_source_name_dict


@module.ui
def binding_ui():
    return ui.div(
        # First row: Description
        ui.div(
            ui.p(
                "This page displays the UpSet plot and correlation matrix for "
                "TF the binding datasets. The current binding datasets are: "
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
                            href="http://younglab.wi.mit.edu/regulatory_code/GWLD.html",
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
                                "Rossi, Matthew J et al. “A high-resolution "
                                "protein architecture of the budding yeast genome.” "
                                "Nature vol. 592,7853 (2021): 309–314. ",
                                ui.a(
                                    "doi:10.1038/s41586-021-03314-8",
                                    href="https://doi.org/10.1038/s41586-021-03314-8",
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
                        "Brent and Mitra labs at Washington University. Most is not "
                        "publicly available yet.",
                    ),
                ),
                ui.p(
                    "More information on how this data was parsed and "
                    "processed for the tfbindingandperturbation database can "
                    "be found ",
                    ui.a(
                        "here",
                        href="https://github.com/cmatKhan/parsing_yeast_database_data",
                        target="_blank",
                    ),
                    ".",
                ),
            ),
            id="binding-description",
        ),
        # Second row: Plot area container
        ui.div(
            # Left: UpSet plot
            ui.div(
                ui.card(
                    ui.card_header("Binding UpSet Plot"),
                    ui.card_body(upset_plot_ui("binding_upset")),
                    ui.card_footer(
                        ui.p(
                            "Click any one of the sets to show what proportion of "
                            "the regulators in the selected set are also present "
                            "in the other sets.",
                            class_="text-muted",
                        ),
                    ),
                ),
                id="binding-upset-container",
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

            #binding-upset-container {
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
    binding upset plot and correlation matrix.

    :param binding_metadata_task: This is the result from a reactive.extended_task.
        Result can be retrieved with .result()
    :param logger: A logger object
    :return: A reactive.calc with the metadata filtered for the selected upset plot sets
        (note that this is not currently working b/c of something to do with the upset
        plot server)

    """
    selected_binding_sets = upset_plot_server(
        "binding_upset",
        metadata_result=binding_metadata_task,
        source_name_dict=get_source_name_dict("binding"),
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
