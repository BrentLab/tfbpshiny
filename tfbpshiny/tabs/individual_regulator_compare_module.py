from logging import Logger

from shiny import Inputs, Outputs, Session, module, reactive, req, ui

from ..rank_response.expression_source_table_module import (
    expression_source_table_server,
    expression_source_table_ui,
)
from ..rank_response.main_table_module import (
    main_table_server,
    main_table_ui,
)
from ..rank_response.replicate_plot_module import (
    rank_response_replicate_plot_server,
    rank_response_replicate_plot_ui,
)
from ..utils.create_accordion_panel import create_accordion_panel

_init_rr_choices = [
    "binding_source",
    "expression_source",
    "univariate_pvalue",
    "univariate_rsquared",
    "dto_fdr",
    "dto_empirical_pvalue",
    "rank_25",
    "rank_50",
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
        "Replicate Details Columns",
        ui.input_checkbox_group(
            "rr_columns",
            label="",
            choices=_init_rr_choices,
            selected=_init_rr_choices,
        ),
        ui.input_action_button(
            "update_table",
            "Update Table",
            class_="btn-primary mt-2",
            style="width: 100%;",
        ),
    )

    option_panels = [
        general_ui_panel,
        rr_columns_panel,
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
                    "tables for a single regulator. Use the sidebar to select the "
                    "regulator of interest. "
                    "Select rows in the main selection table to filter and highlight "
                    "corresponding data in the replicate details tables and plots."
                ),
                ui.tags.ul(
                    ui.tags.li(
                        ui.tags.b("Colored Lines: "),
                        "Each colored line represents a different binding dataset "
                        "replicate for the currently selected regulator.",
                    ),
                    ui.tags.li(
                        ui.tags.b("Random Lines: "),
                        "The random expectation is calculated as the number of "
                        "responsive target genes divided by the total number of "
                        "target genes.",
                    ),
                    ui.tags.li(
                        ui.tags.b("Gray Shaded Area: "),
                        "This area represents the 95% binomial distribution "
                        "confidence interval.",
                    ),
                ),
            ),
            ui.div(
                rank_response_replicate_plot_ui("rank_response_replicate_plot"),
                style="max-width: 100%; overflow-x: auto;",
            ),
            ui.row(
                ui.column(
                    6,
                    ui.card(
                        ui.card_header("Main Selection Table"),
                        main_table_ui("main_table"),
                        ui.card_footer(
                            ui.p(
                                ui.tags.b("How to use: "),
                                "Select rows in this table to filter and highlight "
                                "corresponding data in the replicate details table "
                                "and plots. "
                                "Multiple rows can be selected by holding Ctrl/Cmd "
                                "while clicking.",
                                style="margin: 0; font-size: 0.9em; color: #666;",
                            )
                        ),
                        style="height: 100%;",
                    ),
                ),
                ui.column(
                    6,
                    ui.card(
                        ui.card_header("Replicate Details"),
                        ui.navset_tab(
                            ui.nav_panel(
                                "TFKO",
                                expression_source_table_ui("tfko_table"),
                            ),
                            ui.nav_panel(
                                "Overexpression",
                                expression_source_table_ui("overexpression_table"),
                            ),
                            id="expression_source_tabs",
                        ),
                        ui.card_footer(
                            ui.p(
                                ui.tags.b("Note: "),
                                "Rows corresponding to your main table selection are "
                                "automatically highlighted in orange. "
                                "This table shows detailed metrics for the selected "
                                "expression source. "
                                "Switch between tabs to view different expression "
                                "conditions.",
                                style="margin: 0; font-size: 0.9em; color: #666;",
                            )
                        ),
                        style="height: 100%;",
                    ),
                ),
                style="margin-top: 20px;",
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

    selected_rr_columns: reactive.value[list] = reactive.Value(_init_rr_choices)

    # Reactive to check if there are changes in column selection
    @reactive.calc
    def has_column_changes():
        current_selection = set(input.rr_columns.get() or [])
        confirmed_selection = set(selected_rr_columns.get())
        return current_selection != confirmed_selection

    # Update column choices for replicate details
    @reactive.effect
    def _():
        req(rr_metadata)
        rr_metadata_local = rr_metadata.get()
        cols = list(rr_metadata_local.columns)

        # Remove columns that are now in the main table
        excluded_cols = [
            "genomic_inserts",
            "mito_inserts",
            "plasmid_inserts",
            "promotersetsig",
        ]
        cols = [col for col in cols if col not in excluded_cols]

        # Ensure key columns are first
        priority_cols = ["binding_source", "expression_source"]
        cols = priority_cols + [col for col in cols if col not in priority_cols]

        selected = list(input.rr_columns.get())
        selected = [col for col in selected if col not in excluded_cols]

        ui.update_checkbox_group("rr_columns", choices=cols, selected=selected)

    # Update button appearance based on changes
    @reactive.effect
    def _():
        has_changes = has_column_changes()

        if has_changes:
            # Active state
            ui.update_action_button(
                "update_table",
                label="Update Table",
                disabled=False,
            )

        else:
            # Disabled state
            ui.update_action_button(
                "update_table",
                label="Update Table",
                disabled=True,
            )

    # Update the confirmed column selections when the button is clicked
    @reactive.effect
    @reactive.event(input.update_table)
    def _():
        req(input.rr_columns)
        selected_cols = list(input.rr_columns.get())
        selected_rr_columns.set(selected_cols)
        logger.debug("Updated table columns: %s", selected_cols)

    # Main table with selection capability
    selected_promotersetsigs = main_table_server(
        "main_table",
        rr_metadata=rr_metadata,
        bindingmanualqc_result=bindingmanualqc_result,
        logger=logger,
    )

    # Update the reactive value when main table selection changes
    @reactive.effect
    def _():
        selected_promotersetsigs_local = selected_promotersetsigs()
        selected_promotersetsigs_reactive.set(selected_promotersetsigs_local)
        logger.debug(
            "selected_promotersetsigs_reactive: %s", selected_promotersetsigs_reactive()
        )

    # Expression source tables
    expression_source_table_server(
        "tfko_table",
        rr_metadata=rr_metadata,
        expression_source="kemmeren_tfko",
        selected_promotersetsigs=selected_promotersetsigs_reactive,
        selected_columns=selected_rr_columns,
        logger=logger,
    )

    expression_source_table_server(
        "overexpression_table",
        rr_metadata=rr_metadata,
        expression_source="mcisaac_oe",
        selected_promotersetsigs=selected_promotersetsigs_reactive,
        selected_columns=selected_rr_columns,
        logger=logger,
    )
