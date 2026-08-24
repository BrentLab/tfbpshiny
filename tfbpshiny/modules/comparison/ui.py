"""UI functions for the Comparison module."""

from __future__ import annotations

from shiny import module, ui

from tfbpshiny.components import sidebar_label
from tfbpshiny.modules.comparison.queries import (
    METRIC_DTO,
    METRIC_LABELS,
    METRIC_TOPN,
)


@module.ui
def comparison_ui() -> ui.Tag:
    return ui.layout_sidebar(
        ui.sidebar(
            ui.h2("Comparisons"),
            sidebar_label("Metric"),
            ui.input_radio_buttons(
                "metric",
                label=None,
                choices={
                    METRIC_TOPN: ui.tooltip(
                        ui.span(METRIC_LABELS[METRIC_TOPN]),
                        "Median percent of a regulator's top-N bound targets that are"
                        " transcriptionally responsive.",
                        placement="right",
                    ),
                    METRIC_DTO: ui.tooltip(
                        ui.span(METRIC_LABELS[METRIC_DTO]),
                        "Percent of regulators whose bound and responsive target sets"
                        " overlap more than chance (empirical p < 0.01), out of all"
                        " regulators shared by the two datasets.",
                        placement="right",
                    ),
                },
                selected=METRIC_TOPN,
            ),
            # Top-N and DTO take different parameters, so the rest of the shared
            # controls are rendered per metric rather than shown-and-ignored.
            ui.output_ui("metric_controls"),
            ui.output_ui("tab_specific_controls"),
            id="comparison_sidebar",
            width=320,
            open="open",
        ),
        # Tables recompute live as sidebar controls change; some fetches take a
        # couple of seconds, so show a busy indicator in place of the Execute
        # button that used to signal pending work.
        ui.busy_indicators.use(spinners=True, pulse=True),
        ui.h1("Binding/Perturbation Comparisons"),
        ui.div(
            {"class": "sidebar-text"},
            ui.p(
                "Compare selected binding and perturbation datasets. All comparisons"
                " are faceted by perturbation source; values are median"
                " percent-responsive across regulators."
            ),
            ui.tags.ul(
                ui.tags.li(
                    ui.strong("Compare Datasets:"),
                    " binding vs. perturbation matrix. Each cell shows the median"
                    " percent of top-N binding targets that are transcriptionally"
                    " responsive. Responsive targets are defined by the authors'"
                    " original thresholds. Click row/column headers to view"
                    " distributions.",
                ),
                ui.tags.li(
                    ui.strong("Compare Promoter Definitions:"),
                    " side-by-side tables comparing promoter enrichment scores across"
                    " promoter sets. Rows are binding datasets; columns are promoter"
                    " set definitions. ChIP-chip (Harbison) is absent: its regions are"
                    " microarray probes fixed by the platform, and the source ships"
                    " per-target ratios with no signal track to re-summarise over a"
                    " promoter window, so it has no variant to place in any column.",
                ),
                ui.tags.li(
                    ui.strong("Compare Analysis Methods:"),
                    " one table per perturbation dataset comparing promoter enrichment"
                    " against peak calling over the same promoter definition, for"
                    " ChIP-exo and ChEC-seq datasets. Rows are binding methods;"
                    " columns are promoter set definitions.",
                ),
            ),
            ui.tags.details(
                ui.tags.summary(ui.h4("Binding Methods", style="display:inline;")),
                ui.p(
                    ui.strong("Promoter Enrichment"),
                    " sums the binding signal for a given regulator over a predefined"
                    " promoter region and compares it to a control set of untagged"
                    " random insertions.",
                ),
                ui.p(
                    ui.strong("Original Peaks"),
                    " (Rossi 2021 and Mahendrawada 2025 only) uses the peak-calling"
                    " approach from the original publications. For Rossi 2021, filtered"
                    " high-quality peaks are available at ",
                    ui.tags.a(
                        "yeastepigenome.org",
                        href="https://yeastepigenome.org",
                        target="_blank",
                    ),
                    "; each peak is annotated to the closest ORF within 500 bp, and"
                    " replicates are combined by taking the median score. For"
                    " Mahendrawada 2025, the peak score from the original publication"
                    " is used.",
                ),
                ui.p(
                    ui.strong("Peak Calling"),
                    " is an independent re-calling of peaks from the same raw data,"
                    " intersected with each of the four promoter definitions below."
                    " This makes it directly comparable to promoter enrichment over"
                    " the same window. Rossi 2021 uses MACS; Mahendrawada 2025 uses"
                    " HOMER, replicating the peak-calling method used in the"
                    " reference publication (a peak is kept when it appears in at"
                    " least two replicates). Targets are ranked by the maximum peak"
                    " score within the promoter.",
                ),
            ),
            ui.tags.details(
                ui.tags.summary(
                    ui.h4("Promoter Set Definitions", style="display:inline;")
                ),
                ui.tags.dl(
                    ui.tags.dt(
                        ui.tags.a(
                            "Promoter Set 1 (Kang)",
                            href="https://doi.org/10.1101/gr.259655.119",
                            target="_blank",
                        )
                    ),
                    ui.tags.dd(
                        "700 bp upstream of each start codon, truncated if there"
                        " exists a feature within 700 bp of the ORF."
                    ),
                    ui.tags.dt(
                        ui.tags.a(
                            "Promoter Set 2 (Mindel)",
                            href="https://doi.org/10.1101/2025.10.12.681120",
                            target="_blank",
                        )
                    ),
                    ui.tags.dd(
                        "Promoter regions defined from the start codon to at least"
                        " 700 bp upstream of the TSS defined by Park et al., 2014;"
                        " Pelechano et al., 2013; Policastro et al., 2020 (provided"
                        " in the SGD annotations). If no TSS is defined, the start"
                        " codon is used."
                    ),
                    ui.tags.dt("Promoter Set 3 (500bp)"),
                    ui.tags.dd(
                        "Promoter regions defined as exactly 500 bp upstream of the"
                        " start codon. No truncation or extension; all promoters are"
                        " the same length."
                    ),
                    ui.tags.dt("Promoter Set 4 (Intergenic)"),
                    ui.tags.dd(
                        "Promoter regions defined as the full intergenic region"
                        " upstream of the 5' end of each feature. 1410"
                        " of 6040 features are divergently transcribed."
                    ),
                ),
            ),
        ),
        ui.output_ui("analysis_status"),
        ui.navset_tab(
            # ------------------------------------------------------------------
            # Tab 1: Compare Datasets
            # ------------------------------------------------------------------
            ui.nav_panel(
                "Compare Datasets",
                ui.output_ui("cd_matrix_container"),
                ui.output_ui("cd_distribution_container"),
            ),
            # ------------------------------------------------------------------
            # Tab 2: Compare Promoter Definitions
            # ------------------------------------------------------------------
            ui.nav_panel(
                "Compare Promoter Definitions",
                ui.output_ui("cp_promoter_table"),
            ),
            # ------------------------------------------------------------------
            # Tab 3: Compare Analysis Methods
            # ------------------------------------------------------------------
            ui.nav_panel(
                "Compare Analysis Methods",
                ui.output_ui("cm_method_table"),
            ),
            id="comparison_inner_tabs",
        ),
    )


__all__ = ["comparison_ui"]
