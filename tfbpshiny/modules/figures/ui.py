"""UI for the Figures page."""

from __future__ import annotations

from shiny import module, ui

from tfbpshiny.components import sidebar_label, workspace_heading


@module.ui
def figures_ui() -> ui.Tag:
    return ui.layout_sidebar(
        ui.sidebar(
            ui.h2("Figures"),
            ui.output_ui("tf_selector"),
            ui.input_switch(
                "show_facets",
                ui.tooltip(
                    ui.span("Show all TFs"),
                    "Draws the rank-response curve for every TF in the intersection"
                    " as a small-multiples grid (~60-70 panels). Off by default"
                    " because it is the slowest thing on the page.",
                    placement="right",
                ),
                value=False,
            ),
            sidebar_label("Responsiveness"),
            ui.input_radio_buttons(
                "scoring",
                label=None,
                choices={
                    "Relaxed": ui.tooltip(
                        ui.span("Relaxed"),
                        "Uniform |effect| > 0 and p < 0.05.",
                        placement="right",
                    ),
                    "Stringent": ui.tooltip(
                        ui.span("Stringent"),
                        "Each dataset's own published criteria, resolved per"
                        " dataset (e.g. TFKO |Madj| > log2(1.7) and p < 0.05;"
                        " degron |log2FC| > log2(1.3) and padj < 0.1).",
                        placement="right",
                    ),
                },
                selected="Relaxed",
            ),
            sidebar_label("Top N"),
            ui.input_radio_buttons(
                "box_top_n",
                label=None,
                choices={"10": "10", "25": "25", "50": "50", "75": "75", "100": "100"},
                selected="25",
                inline=True,
            ),
            id="figures_sidebar",
            width=320,
            open="open",
        ),
        # Figures recompute from the database on demand; some take a moment.
        ui.busy_indicators.use(spinners=True, pulse=True),
        ui.div(
            {"class": "workspace-centered"},
            workspace_heading("Figures"),
            ui.div(
                {"class": "sidebar-text"},
                ui.p(
                    "Publication figures computed live from the materialized"
                    " database. Each figure states the TF set it is drawn over;"
                    " those sets are intersections, so they are smaller than any"
                    " single dataset."
                ),
            ),
            ui.output_ui("figure_status"),
            workspace_heading("1. Rank vs. response"),
            ui.div(
                {"class": "sidebar-text"},
                ui.p(
                    "Percent of top-n binding targets that are transcriptionally"
                    " responsive, as a function of n. One panel per perturbation"
                    " dataset, one line per binding dataset. Lower ranks generally"
                    " correspond to lower response rates."
                ),
                ui.p(
                    ui.tags.em(
                        "The x axis is the number of targets actually summarised,"
                        " not the nominal cutoff: ties at the cutoff let slightly"
                        " more than n targets through."
                    )
                ),
                ui.p(
                    ui.tags.strong("A line may show fewer than five points."),
                    " Targets are ranked with ties sharing a rank, so when many"
                    " targets tie at the top, several cutoffs return the same set"
                    " and collapse to a single point. Calling Cards is the usual"
                    " cause: its Poisson p-values underflow to exactly 0 for the"
                    " most strongly bound targets, so those targets are"
                    " indistinguishable by rank. CBF1 is the extreme case — 87 of"
                    " its targets share a p-value of 0, so the top-10, 25, 50 and 75"
                    " cutoffs all return the same 82 targets and plot as one point."
                    " Across all Calling Cards samples the median tie at the top is"
                    " only 3 targets, so most regulators are unaffected.",
                ),
                ui.p(
                    ui.tags.em(
                        "This affects the underlying top-N analysis too, not just"
                        " this figure: where a tie is large, a nominal top 25 is"
                        " really a larger and more marginal target set than the"
                        " other datasets', so read that line's response rate as"
                        " being measured over a different-sized set."
                    )
                ),
            ),
            ui.output_ui("fig_rank_response"),
            ui.output_ui("fig_rank_response_facets"),
            workspace_heading("2. Response rate among top binding targets"),
            ui.div(
                {"class": "sidebar-text"},
                ui.p(
                    "Distribution across TFs of the percent responsive among the"
                    " top-N binding targets. One panel per perturbation dataset,"
                    " one box per binding dataset. Points are outliers only."
                ),
                ui.p(
                    ui.tags.em(
                        "The Responsiveness selector changes what counts as"
                        " responsive. Stringent applies each dataset's published"
                        " criteria, so its boxes sit well below Relaxed's."
                    )
                ),
            ),
            ui.output_ui("fig_topn_boxes"),
            workspace_heading("3. Authors' binding thresholds"),
            ui.div(
                {"class": "sidebar-text"},
                ui.p(
                    "For the two datasets whose authors published a binary binding"
                    " call, the response rate over every bound target alongside the"
                    " number of bound targets per TF. A tighter threshold shows as a"
                    " higher response rate with fewer targets."
                ),
                ui.p(
                    ui.tags.em(
                        "ChIP-chip and Calling Cards are absent: they have p-value"
                        " columns but no cutoff documented in any datacard, so there"
                        " is no authors' threshold to apply. Filled boxes read the"
                        " left axis, hollow boxes the right."
                    )
                ),
            ),
            ui.output_ui("fig_authors_bound"),
            workspace_heading("4. Direct target overlap significance"),
            ui.div(
                {"class": "sidebar-text"},
                ui.p(
                    "Number of TFs whose bound and responsive target sets overlap"
                    " more than chance (DTO empirical p < 0.01), with the same"
                    " count as a fraction of the TFs shared by the two datasets."
                ),
            ),
            ui.output_ui("fig_dto_bars"),
            workspace_heading("5. Agreement on DTO significance"),
            ui.div(
                {"class": "sidebar-text"},
                ui.p(
                    "How many TFs are DTO-significant in one, two or all three"
                    " binding datasets. Restricted to TFs shared by all three"
                    " binding datasets and the perturbation dataset, so the region"
                    " outside every circle is meaningful."
                ),
            ),
            ui.output_ui("fig_dto_venn"),
            workspace_heading("6. Agreement between datasets is modest"),
            ui.div(
                {"class": "sidebar-text"},
                ui.p(
                    "How much two datasets of the same type agree, measured as the"
                    " overlap of their top-N target sets against the overlap chance"
                    " would give. Zero means no better than chance."
                ),
                ui.p(
                    ui.tags.em(
                        "Each TF's curve is collapsed to one number by weighting"
                        " each N by 1/N, so the top of the ranking dominates."
                        " Perturbation datasets are ranked by absolute effect, so"
                        " knockout and overexpression are comparable."
                    )
                ),
            ),
            # Collapsed by default: the default selection answers the figure's
            # headline question, and 21 binding checkboxes would otherwise dominate
            # the section. Opening it is how a reader compares promoter definitions
            # or calling methods instead of assays.
            ui.accordion(
                ui.accordion_panel(
                    "Choose datasets to compare",
                    ui.div(
                        {"class": "sidebar-text"},
                        ui.p(
                            "Every pair among the selected datasets is drawn. Pick"
                            " one promoter definition across assays to compare"
                            " assays; pick several definitions of one assay to"
                            " compare promoter definitions; pick an assay's"
                            " enrichment and peak rows to compare calling methods."
                            " Mixing more than one of those at a time gives pairs"
                            " that differ in two ways at once and cannot be"
                            " attributed to either."
                        ),
                        ui.p(
                            ui.tags.em(
                                "The authors' original peak calls are not listed."
                                " Their regions come from the publication's own"
                                " pipeline rather than a fixed upstream window, so"
                                " any pair involving one differs in both the caller"
                                " and the region. The promoter-set-matched re-calls"
                                " (rows ending in 'peaks') carry the same"
                                " information against a defined window."
                            )
                        ),
                    ),
                    ui.output_ui("agreement_dataset_picker"),
                    value="agreement_datasets",
                ),
                id="agreement_accordion",
                open=False,
                multiple=False,
            ),
            ui.output_ui("fig_agreement"),
        ),
    )


__all__ = ["figures_ui"]
