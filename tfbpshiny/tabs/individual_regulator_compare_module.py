from logging import Logger

from shiny import Inputs, Outputs, Session, module, reactive, render, ui

from ..rank_response.expression_source_table_module import (
    DEFAULT_RR_COLUMNS,
    RR_CHOICES_DICT,
    expression_source_table_server,
    expression_source_table_ui,
)
from ..rank_response.main_table_module import (
    DEFAULT_MAIN_TABLE_COLUMNS,
    MAIN_TABLE_CHOICES_DICT,
    main_table_server,
    main_table_ui,
)
from ..rank_response.replicate_plot_module import (
    rank_response_replicate_plot_overexpression_ui,
    rank_response_replicate_plot_server,
    rank_response_replicate_plot_tfko_ui,
)
from ..utils.create_accordion_panel import create_accordion_panel

    def rr_plot_panel(label, output_id):
        """
        Create a panel for rank response plots with a specific label and output ID.
        """
        return ui.nav_panel(
            label,
            ui.div(
                ui.output_ui(output_id),
                style="max-width: 100%; overflow-x: auto;",
            ),
        )

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

    main_table_columns_panel = create_accordion_panel(
        "Main Table Columns",
        ui.input_checkbox_group(
            "main_table_columns",
            label="QC and Insert Metrics",
            choices=MAIN_TABLE_CHOICES_DICT,
            selected=DEFAULT_MAIN_TABLE_COLUMNS,
        ),
    )

    rr_columns_panel = create_accordion_panel(
        "Replicate Details Columns",
        ui.input_checkbox_group(
            "rr_columns",
            label="Replicate Metrics",
            choices=RR_CHOICES_DICT,
            selected=DEFAULT_RR_COLUMNS,
        ),
    )

    update_button_ui = (
        ui.input_action_button(
            "update_tables",
            "Update Tables",
            class_="btn-primary mt-2",
            style="width: 100%;",
        ),
    )

    option_panels = [
        general_ui_panel,
        main_table_columns_panel,
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
            update_button_ui,
            width="300px",
        ),
        ui.div(
            ui.div(
                ui.p(
                    "This page displays the rank response plots and associated "
                    "tables for a single regulator. Use the sidebar to select the "
                    "regulator of interest and the columns to be displayed in the ",
                    ui.tags.b("Main Selection Table"),
                    " and ",
                    ui.tags.b("Replicate Details Tables"),
                    ". Hover over any of the column names "
                    "for information on what the column represents. ",
                    "Select row(s) in the ",
                    ui.tags.b("Main Selection Table"),
                    " on the right "
                    "to isolate a sample/samples in the plots and highlight the "
                    "corresponding rows in the replicate details table.",
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
            ui.row(
                ui.column(
                    7,
                    ui.card(
                        ui.card_header("Rank Response Plots"),
                        ui.navset_tab(
                            *[
                                rr_plot_panel("TFKO", "tfko_plots"),
                                rr_plot_panel("Overexpression", "overexpression_plots"),
                            ],
                            id="plot_tabs",
                        ),
                    ),
                ),
                ui.column(
                    5,
                    ui.card(
                        ui.card_header("Main Selection Table"),
                            ui.div(
                                main_table_ui("main_table"),
                                style="overflow: auto; width: 100%;",
                        ),
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
                        style="display: flex; flex-direction: column; height: 100%; min-height: 0;",
                    ),
                ),
                style="height: 500px",
            ),
            ui.div(
                ui.card(
                    ui.card_header("Replicate Details Table"),
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
                            "automatically highlighted in aqua. "
                            "This table shows detailed metrics for the selected "
                            "expression source. "
                            "Switch between tabs to view different expression "
                            "conditions.",
                            style="margin: 0; font-size: 0.9em; color: #666;",
                        )
                    ),
                    style="height: 400px;",
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
    # this reactive stores the selected promotersetsigs from the main table server.
    # This needs to be a reactive.value at the top in order to be shared across modules
    # which must be coded before the main table server is called.
    selected_promotersetsigs_reactive: reactive.value[set] = reactive.Value(set())

    # This reactive stores the columns selected from the side bar for
    # the rank response table
    selected_rr_columns: reactive.value[list] = reactive.Value(DEFAULT_RR_COLUMNS)

    # This reactive stores the columns selected from the side bar for
    # the main table
    selected_main_table_columns: reactive.value[list] = reactive.Value(
        DEFAULT_MAIN_TABLE_COLUMNS
    )

    # Create reactive.calc versions for the table modules
    @reactive.calc
    def selected_main_table_columns_calc():
        return selected_main_table_columns.get()

    @reactive.calc
    def selected_rr_columns_calc():
        return selected_rr_columns.get()

    @reactive.effect
    def _():
        """Update the regulator ui drop down selector based on the
        rank_response_metadata."""
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

    rr_metadata = rank_response_replicate_plot_server(
        "rank_response_replicate_plot",
        selected_regulator=input.regulator,
        selected_promotersetsigs=selected_promotersetsigs_reactive,
        logger=logger,
    )

    @reactive.calc
    def has_column_changes():
        """Reactive to check if there are changes in column selection."""
        current_main_selection = set(input.main_table_columns.get() or [])
        confirmed_main_selection = set(selected_main_table_columns.get())

        current_rr_selection = set(input.rr_columns.get() or [])
        confirmed_rr_selection = set(selected_rr_columns.get())

        return (
            current_rr_selection != confirmed_rr_selection
            or current_main_selection != confirmed_main_selection
        )

    @reactive.effect
    def _():
        """Update column choices for main table."""
        selected = list(input.main_table_columns.get())

        ui.update_checkbox_group("main_table_columns", selected=selected)

    @reactive.effect
    def _():
        """Update column choices for replicate details."""
        selected = list(input.rr_columns.get())

        ui.update_checkbox_group("rr_columns", selected=selected)

    # Update button appearance based on changes
    @reactive.effect
    def _():
        has_changes = has_column_changes()

        ui.update_action_button(
            "update_tables",
            label="Update Tables",
            disabled=not has_changes,
        )

    # Update the confirmed column selections when the button is clicked
    @reactive.effect
    @reactive.event(input.update_tables)
    def _():

        selected_rr_cols = list(input.rr_columns.get())
        selected_rr_columns.set(selected_rr_cols)

        selected_main_cols = list(input.main_table_columns.get())
        selected_main_table_columns.set(selected_main_cols)

        logger.debug("Updated replicate details columns: %s", selected_rr_cols)
        logger.debug("Updated main table columns: %s", selected_main_cols)

    # Main table with selection capability
    selected_promotersetsigs = main_table_server(
        "main_table",
        rr_metadata=rr_metadata,
        bindingmanualqc_result=bindingmanualqc_result,
        selected_columns=selected_main_table_columns_calc,
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
        selected_columns=selected_rr_columns_calc,
        logger=logger,
    )

    expression_source_table_server(
        "overexpression_table",
        rr_metadata=rr_metadata,
        expression_source="mcisaac_oe",
        selected_promotersetsigs=selected_promotersetsigs_reactive,
        selected_columns=selected_rr_columns_calc,
        logger=logger,
    )

    # Synchronize plot tabs and expression source table tabs
    @reactive.effect
    def _():
        """Update expression source table tab when plot tab changes."""
        plot_tab = input.plot_tabs()
        if plot_tab:
            ui.update_navs("expression_source_tabs", selected=plot_tab)

    @reactive.effect
    def _():
        """Update plot tab when expression source table tab changes."""
        table_tab = input.expression_source_tabs()
        if table_tab:
            ui.update_navs("plot_tabs", selected=table_tab)

    # Render plots for different expression sources
    @render.ui
    def tfko_plots():
        # Return the plots filtered for TFKO expression source
        return rank_response_replicate_plot_tfko_ui("rank_response_replicate_plot")

    @render.ui
    def overexpression_plots():
        # Return the plots filtered for overexpression source
        return rank_response_replicate_plot_overexpression_ui(
            "rank_response_replicate_plot"
        )
