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
def perturbation_response_ui():
    return ui.div(
        # First row: Description
        ui.div(
            ui.p(
                "This page displays the UpSet plot and correlation matrix for "
                "TF perturbation response datasets. The current datasets include "
                "data derived from gene deletions and overexpression methods."
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
                        "currently displaying results for the 15 minute time point. "
                        "The data is publicly available from: ",
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
                                "Molecular systems biology vol. 16,3 (2020): e9174. ",
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
                                "Benschop JJ, Lenstra TL, Margaritis T, O'Duibhir E, "
                                "Apweiler E, van Wageningen S, Ko CW, et al. 2014. "
                                "Large-scale genetic perturbations reveal regulatory "
                                "networks and an abundance of gene-specific "
                                "repressors. Cell 157: 740–752.",
                                ui.a(
                                    "doi:10.1016/j.cell.2014.02.054",
                                    href="https://doi.org/10.1016/j.cell.2014.02.054",
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
                                "Saccharomyces cerevisiae reveals many new targets.'"
                                " Nucleic acids research vol. 38,14 (2010): 4768-77. ",
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
            id="perturbation-description",
        ),
        # Second row: Plot area container
        ui.div(
            # Left: UpSet plot
            ui.div(
                ui.card(
                    ui.card_header("Perturbation Response UpSet Plot"),
                    ui.card_body(upset_plot_ui("perturbation_response_upset")),
                    ui.card_footer(
                        ui.p(
                            "Click any one of the sets to show what proportion of "
                            "the regulators in the selected set are also present "
                            "in the other sets.",
                            class_="text-muted",
                        ),
                    ),
                ),
                id="perturbation-upset-container",
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
                            "Click and drag to zoom in on a specific region of the "
                            "correlation matrix. Double click to reset the zoom.",
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

            #perturbation-upset-container {
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
    perturbation response upset plot and correlation matrix for the perturbation
    response data.

    :param pr_metadata_task: This is the result from a reactive.extended_task. Result
        can be retrieved with .result()
    :param logger: A logger object
    :return: A reactive.calc with the metadata filtered for the selected upset plot sets
        (note that this is not currently working b/c of something to do with the upset
        plot server)

    """

    # TODO: retrieving the response should be from the db as a reactive.extended_task
    tf_pr_df = pd.read_csv("tmp/shiny_data/response_data.csv")
    tf_pr_df.set_index("target_symbol", inplace=True)
    correlation_matrix_server(
        "perturbation_corr_matrix",
        tf_binding_df=tf_pr_df,
        logger=logger,
    )

    selected_pr_sets = upset_plot_server(
        "perturbation_response_upset",
        metadata_result=pr_metadata_task,
        source_name_dict=get_source_name_dict("perturbation_response"),
        logger=logger,
    )

    @reactive.effect
    def _():
        logger.info(f"Selected perturbation response sets: {selected_pr_sets()}")

    return selected_pr_sets
