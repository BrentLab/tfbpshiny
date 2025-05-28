from logging import Logger

from shiny import Inputs, Outputs, Session, module, reactive, req, ui

from ..misc.bindingmanualqc_table_module import (
    bindingmanualqc_table_server,
    bindingmanualqc_table_ui,
)
from ..rank_response.replicate_plot_module import (
    rank_response_replicate_plot_server,
    rank_response_replicate_plot_ui,
)
from ..rank_response.replicate_table_module import (
    rank_response_replicate_table_server,
    rank_response_replicate_table_ui,
)
from ..utils.create_accordion_panel import create_accordion_panel

_init_rr_choices = [
    "promotersetsig",
    "expression",
    "binding_source",
    "expression_source",
    "univariate_pvalue",
    "univariate_rsquared",
    "dto_fdr",
    "dto_empirical_pvalue",
    "rank_25",
    "rank_50",
    "genomic_inserts",
    "mito_inserts",
    "plasmid_inserts",
]

_init_bindingmanualqc_choices = [
    "promotersetsig",
    "dto_status",
    "rank_response_status",
]


@module.ui
def individual_regulator_compare_ui():

    general_ui_panel = create_accordion_panel(
        "General",
        ui.input_switch(
            "symbol_locus_tag_switch", label="Symbol/Locus Tag", value=False
        ),
        ui.input_select(
            "regulator",
            label="Select Regulator",
            selectize=True,
            selected=None,
            choices=[],
        ),
    )

    rr_columns_panel = create_accordion_panel(
        "RR Replicate Columns",
        ui.input_checkbox_group(
            "rr_columns",
            label="",
            choices=_init_rr_choices,
            selected=_init_rr_choices,
        ),
    )

    bindingmanualqc_columns_panel = create_accordion_panel(
        "BindingManualQC Columns",
        ui.input_checkbox_group(
            "bindingmanualqc_columns",
            label="",
            choices=_init_bindingmanualqc_choices,
            selected=_init_bindingmanualqc_choices,
        ),
    )

    option_panels = [
        general_ui_panel,
        rr_columns_panel,
        bindingmanualqc_columns_panel,
    ]

    return ui.layout_sidebar(
        ui.sidebar(
            ui.accordion(
                *option_panels,
                id=module.resolve_id("input_accordion"),
                open=None,
                multiple=True,
            ),
            width="400px",
        ),
        ui.div(
            ui.div(
                ui.p(
                    "This page displays the rank response plots and associated "
                    "Rank Response and Binding Manual Quality Control tables for a "
                    "single regulator. Use the sidebar to select the regulator of "
                    "interest, Rank Response columns, and Binding Manual Quality "
                    "Control columns. "
                    "Once the options are selected, the rank response plots and tables "
                    "will be updated to display the data for the selected regulator. "
                    "Select rows on the rank response table to highlight the "
                    "corresponding data on the plots, and the Binding Manual Quality "
                    "table will be filtered to show the corresponding rows."
                ),
                ui.tags.ul(
                    ui.tags.li(
                        ui.tags.b("Colored Lines: "),
                        "Each colored line represents a different binding dataset replicate for "
                        "the currently selected regulator.",
                    ),
                    ui.tags.li(
                        ui.tags.b("Random Lines: "),
                        "The random expectation is calculated as the number of responsive target genes"
                        "divided by the total number of target genes",
                    ),
                    ui.tags.li(
                        ui.tags.b("Gray Shaded Area: "),
                        "This area represents the 95% binomial distribution confidence interval",
                    ),
                ),
            ),
            ui.div(
                rank_response_replicate_plot_ui("rank_response_replicate_plot"),
                rank_response_replicate_table_ui("rank_response_replicate_table"),
                bindingmanualqc_table_ui("bindingmanualqc_table"),
                style="max-width: 100%; overflow-x: auto;",
            ),
        ),
    )


@module.server
def individual_regulator_compare_server(
    input: Inputs,
    output: Outputs,
    session: Session,
    *,
    rank_response_metadata: reactive.ExtendedTask,
    bindingmanualqc_result: reactive.ExtendedTask,
    logger: Logger,
) -> None:
    """
    This function produces the reactive/render functions necessary to producing the
    individual_regulator_compare module which inclues the rank response plots and
    associated QC tables.

    :param rank_response_metadata: This is the result from a reactive.extended_task.
        Result can be retrieved with .result()
    :param bindingmanualqc_result: This is the result from a reactive.extended_task.
        Result can be retrieved with .result()
    :param logger: A logger object

    """
    selected_promotersetsigs_reactive: reactive.value[set] = reactive.Value(set())

    @reactive.effect
    def _():
        rank_response_metadata_local = rank_response_metadata.result()

        input_switch_value = input.symbol_locus_tag_switch.get()

        logger.info("switch: %s", input_switch_value)

        regulator_col = (
            "regulator_symbol" if input_switch_value else "regulator_locus_tag"
        )

        logger.info("regulator_col: %s", regulator_col)

        regulator_dict = (
            rank_response_metadata_local[["regulator_id", regulator_col]]
            .drop_duplicates()
            .sort_values(by=regulator_col)
            .set_index("regulator_id")
            .to_dict(orient="dict")
        )

        logger.info("regulator_dict: %s", regulator_dict.keys())

        ui.update_select("regulator", choices=regulator_dict)

    @reactive.effect
    def _():
        x = input.regulator.get()
        logger.debug("regulator: %s", x)

    rr_metadata = rank_response_replicate_plot_server(
        "rank_response_replicate_plot",
        selected_regulator=input.regulator,
        selected_promotersetsigs=selected_promotersetsigs_reactive,
        logger=logger,
    )

    # update the rr_metadata column options
    @reactive.effect
    def _():
        rr_metadata_local = rr_metadata.get()
        cols = list(rr_metadata_local.columns)
        # this is a messy way to ensure that these columns are always first
        cols = [
            "promotersetsig",
            "binding_source",
            "expression_source",
        ] + [
            col
            for col in cols
            if col not in ["promotersetsig", "binding_source", "expression_source"]
        ]
        selected = list(input.rr_columns.get())

        ui.update_checkbox_group("rr_columns", choices=cols, selected=selected)

    # update the bindingmanualqc column options
    @reactive.effect
    def _():
        bindingmanualqc_local = bindingmanualqc_result.result()
        cols = list(bindingmanualqc_local.columns) + ["promotersetsig"]
        selected = list(input.bindingmanualqc_columns.get())

        ui.update_checkbox_group(
            "bindingmanualqc_columns", choices=cols, selected=selected
        )

    @reactive.calc
    def rr_display_table():
        req(rr_metadata)
        selected_rr_cols = list(input.rr_columns.get())
        rr_metadata_local = rr_metadata.get()
        rr_metadata_local.sort_values(
            by="promotersetsig", ascending=False, inplace=True
        )
        logger.debug(f"rr selected columns: {selected_rr_cols}")

        df = rr_metadata_local[selected_rr_cols]
        logger.debug(f"display rr metadata columns: {df.columns}")

        return df

    selected_promotersetsigs = rank_response_replicate_table_server(
        "rank_response_replicate_table", rr_metadata=rr_display_table, logger=logger
    )

    @reactive.effect
    def _():
        selected_promotersetsigs_local = selected_promotersetsigs()
        selected_promotersetsigs_reactive.set(selected_promotersetsigs_local)
        logger.debug(
            "selected_promotersetsigs_reactive: %s", selected_promotersetsigs_reactive()
        )

    @reactive.calc
    def bindingmanualqc_subset_df():
        # use the promotersetsig in rr_metadata to subset the bindingmanualqc table
        # by right joining to rr_metadata on single_binding and composite_binding
        rr_metadata_local = rr_metadata.get()
        bindingmanualqc_local = bindingmanualqc_result.result()
        # this is used in a query statement
        selected_promotersetsigs_local = selected_promotersetsigs()

        logger.debug("bindingmanualqc_subset_df: %s", bindingmanualqc_local)
        logger.debug("rr_metadata: %s", rr_metadata_local)

        bindingmanualqc_subset = (
            bindingmanualqc_local.merge(
                rr_metadata_local[
                    ["promotersetsig", "single_binding", "composite_binding"]
                ],
                how="right",
                left_on=["single_binding", "composite_binding"],
                right_on=["single_binding", "composite_binding"],
            )
            .drop_duplicates()
            .sort_values(by="promotersetsig", ascending=False)
        )

        # Now filter using regular Python variable logic
        bindingmanualqc_subset = bindingmanualqc_subset[
            bindingmanualqc_subset["promotersetsig"].isin(
                selected_promotersetsigs_local
            )
        ].reset_index(drop=True)

        logger.debug("bindingmanualqc_subset: %s", bindingmanualqc_subset)

        selected_bindingmanualqc_cols = list(input.bindingmanualqc_columns.get())
        logger.debug(
            f"bindingmanualqc selected columns: {selected_bindingmanualqc_cols}"
        )
        return bindingmanualqc_subset[selected_bindingmanualqc_cols]

    bindingmanualqc_table_server(
        "bindingmanualqc_table",
        bindingmanualqc_df=bindingmanualqc_subset_df,
        logger=logger,
    )
