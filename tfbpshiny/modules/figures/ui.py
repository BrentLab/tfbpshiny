"""UI for the Figures page."""

from __future__ import annotations

from shiny import module, ui

from tfbpshiny.components import sidebar_label, workspace_heading
from tfbpshiny.modules.figures.queries import (
    AGREEMENT_HALF_LIFE_DEFAULT,
    AGREEMENT_HALF_LIFE_MAX,
    AGREEMENT_HALF_LIFE_MIN,
    AGREEMENT_HALF_LIFE_STEP,
)


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
                selected="Stringent",
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
                        " not the nominal cutoff: a group of tied targets is in the"
                        " top n only if its average rank is within n, so a group can"
                        " carry the count past n or leave it short."
                    )
                ),
                ui.p(
                    ui.tags.strong("A line may show fewer than five points."),
                    " When many targets tie at the top, a cutoff can fall inside the"
                    " tie group without reaching its average rank, and that cutoff"
                    " then has no point; later cutoffs that include the whole group"
                    " return the same set and collapse to a single point. Calling"
                    " Cards is the usual cause: its Poisson p-values underflow to"
                    " exactly 0 for the most strongly bound targets, so those targets"
                    " are indistinguishable by rank. CBF1 is the extreme case — 87 of"
                    " its targets share a p-value of 0 (average rank 44), so the"
                    " top-10 and top-25 cutoffs have no point, and the top-50, 75 and"
                    " 100 cutoffs all return the same 87 targets and plot as one"
                    " point. Across all Calling Cards samples the median tie at the"
                    " top is only 3 targets, so most regulators are unaffected.",
                ),
                ui.p(
                    ui.tags.em(
                        "This affects the underlying top-N analysis too, not just"
                        " this figure: where a tie is large, a nominal top 25 may be"
                        " a shorter list than the other datasets', so read that"
                        " line's response rate as being measured over a different-"
                        " sized set."
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
                    "For each binding dataset, the response rate over every bound"
                    " target alongside the number of bound targets per TF. Bound"
                    " means the authors' own peak call for Rossi and Mahendrawada,"
                    " and a p-value threshold for the two datasets that only report"
                    " one. A tighter threshold shows as a higher response rate with"
                    " fewer targets."
                ),
                ui.p(
                    ui.tags.em(
                        "ChIP-chip uses p <= 0.001 (YPD samples) and Calling Cards a"
                        " Poisson p-value < 1e-4; both thresholds were chosen for this"
                        " figure rather than published as a binary call by the"
                        " authors."
                    )
                ),
            ),
            ui.output_ui("fig_authors_bound"),
            workspace_heading("4. Direct target overlap significance"),
            ui.div(
                {"class": "sidebar-text"},
                ui.p(
                    "Percent of TFs shared by a binding and perturbation dataset"
                    " whose bound and responsive target sets overlap more than"
                    " chance (DTO empirical p < 0.01). The label above each bar"
                    " is that percentage's raw counts, DTO-significant TFs over"
                    " shared TFs."
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
                ui.p(
                    ui.tags.em(
                        "Circle areas are only exactly proportional to set sizes"
                        " when a valid three-circle arrangement exists for them --"
                        " it does not always. 'Cost-based' trades that exactness"
                        " for robustness: it stays approximately proportional on"
                        " sizes the default layout cannot represent exactly,"
                        " instead of falling back to equal circles."
                    )
                ),
            ),
            ui.input_radio_buttons(
                "dto_venn_layout",
                label=None,
                choices={
                    "default": "Default",
                    "cost_based": "Cost-based (proportional)",
                },
                selected="default",
                inline=True,
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
                        "By default, every binding series compares each assay's 500"
                        " bp promoter-window variant, so series are named after the"
                        ' dataset alone (e.g. "2021 ChIP-exo"). A series only'
                        " names its promoter set when it isn't 500 bp -- picking Kang,"
                        " Mindel or Intergenic below -- and only names its method"
                        " when it's peak calling rather than promoter enrichment."
                    )
                ),
                ui.p(
                    ui.tags.em(
                        "Each TF's curve is collapsed to one number by weighting"
                        " each cutoff exponentially, so the top of the ranking"
                        " dominates. The half-life below is how far N has to rise"
                        " for a cutoff's influence to halve: small values judge the"
                        " datasets on their very top targets, large values weight"
                        " the whole range almost evenly. Binding and perturbation"
                        " get separate sliders, since the two are ranked on"
                        " different quantities and need not decay at the same"
                        " rate. The solid grey line on each curve panel"
                        " illustrates that panel's weight on its own right-hand"
                        " scale -- it does not change the enrichment curves,"
                        " only the box plot's weighted mean. Perturbation"
                        " datasets are ranked by absolute effect, so knockout and"
                        " overexpression are comparable."
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
            # Each slider sits directly above the plot it controls, rather than both
            # stacked above both plots -- makes which slider affects which row
            # unambiguous.
            ui.div(
                ui.input_slider(
                    "agreement_half_life_binding",
                    "Binding weighting half-life (in units of N)",
                    min=AGREEMENT_HALF_LIFE_MIN,
                    max=AGREEMENT_HALF_LIFE_MAX,
                    value=AGREEMENT_HALF_LIFE_DEFAULT,
                    step=AGREEMENT_HALF_LIFE_STEP,
                    ticks=False,
                ),
                style="max-width: 420px; margin-bottom: 0.5rem;",
            ),
            ui.output_ui("fig_agreement_binding"),
            ui.div(
                ui.input_slider(
                    "agreement_half_life_perturbation",
                    "Perturbation weighting half-life (in units of N)",
                    min=AGREEMENT_HALF_LIFE_MIN,
                    max=AGREEMENT_HALF_LIFE_MAX,
                    value=AGREEMENT_HALF_LIFE_DEFAULT,
                    step=AGREEMENT_HALF_LIFE_STEP,
                    ticks=False,
                ),
                style="max-width: 420px; margin-top: 1.5rem; margin-bottom: 0.5rem;",
            ),
            ui.output_ui("fig_agreement_perturbation"),
            workspace_heading("7. Promoter definitions, response rate"),
            ui.div(
                {"class": "sidebar-text"},
                ui.p(
                    "Distribution across TFs of the top-N percent responsive, one"
                    " box per promoter set (Kang, Mindel, 500 bp, Intergenic),"
                    " scored by promoter enrichment throughout. Faceted by binding"
                    " dataset (rows) and perturbation dataset (columns) -- the same"
                    " comparison as the Comparison page's \"Compare Promoter"
                    ' Definitions" table, shown here as a distribution rather than'
                    " its median."
                ),
                ui.p(
                    ui.tags.em(
                        "TFs are the same for every box in a column: those shared"
                        " by Calling Cards, Rossi ChIP-exo, Mahendrawada ChEC-seq"
                        " and that column's perturbation dataset. The"
                        " Responsiveness and Top N selectors above change what"
                        " counts as responsive and which cutoff is shown."
                    )
                ),
            ),
            ui.output_ui("fig_promoter_boxes"),
            workspace_heading("8. Promoter definitions, DTO significance"),
            ui.div(
                {"class": "sidebar-text"},
                ui.p(
                    "Same grid as figure 7, but each bar is the percent of that"
                    " (binding, perturbation) pair's shared TFs whose bound and"
                    " responsive target sets overlap more than chance (DTO"
                    " empirical p < 0.01), one bar per promoter set. The label"
                    " above each bar is that percentage's raw counts,"
                    " DTO-significant TFs over shared TFs."
                ),
                ui.p(
                    ui.tags.em(
                        "DTO is not sample-filtered, top-N or responsiveness-preset"
                        " dependent -- it is a fixed, pre-computed empirical test,"
                        " the same one figures 4 and 5 already use. Each bar's own"
                        " TF population is whatever DTO actually tested for that"
                        " specific (binding, perturbation) pair, which can differ"
                        " slightly from figure 7's."
                    )
                ),
            ),
            ui.output_ui("fig_dto_significance_grid"),
            workspace_heading("9. Peak calling vs. promoter enrichment"),
            ui.div(
                {"class": "sidebar-text"},
                ui.p(
                    "The same two comparisons as figures 7 and 8, but instead of"
                    " varying the promoter set (with promoter enrichment"
                    " throughout), the 500 bp promoter set is used throughout and"
                    " the two bars per cell are the binding method: promoter"
                    " enrichment vs. peak calling. Top grid: top-N percent"
                    " responsive. Bottom grid: percent of shared TFs that are"
                    " DTO-significant, the same metric as figure 8."
                ),
                ui.p(
                    ui.tags.em(
                        "Only Rossi ChIP-exo and Mahendrawada ChEC-seq have a"
                        " peak-calling arm -- Calling Cards does not, so it is"
                        " absent from this grid rather than shown empty."
                    )
                ),
            ),
            ui.output_ui("fig_method_boxes"),
            workspace_heading("10. Targets shared between datasets"),
            ui.div(
                {"class": "sidebar-text"},
                ui.p(
                    "The targets each dataset ranks in its top N (the Top N"
                    " selector), for the featured TF as a Venn diagram on the left"
                    " and, on the right, the distribution across TFs of how many"
                    " targets each pair of datasets has in common. This is the raw"
                    " overlap behind figure 6, which reports it as enrichment over"
                    " chance, and each pair keeps its figure 6 colour."
                ),
                ui.p(
                    ui.tags.em(
                        "Binding datasets are the 500 bp promoter-enrichment"
                        " variants. Samples follow the dataset filters, which by"
                        " default leave one sample per TF in each dataset."
                    )
                ),
            ),
            ui.output_ui("fig_shared_targets_binding"),
            ui.output_ui("fig_shared_targets_perturbation"),
        ),
    )


__all__ = ["figures_ui"]
