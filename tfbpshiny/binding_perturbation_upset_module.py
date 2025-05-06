import re
from logging import Logger

import pandas as pd
from shiny import Inputs, Outputs, Session, module, reactive, req, ui
from shinywidgets import output_widget, render_widget
from upsetjs_jupyter_widget import UpSetJSWidget


@module.ui
def upset_plot_ui():
    return ui.card(
        output_widget("upset_plot"),
        fill=False,
    )


@module.server
def upset_plot_server(
    input: Inputs,
    output: Outputs,
    session: Session,
    *,
    metadata_result: reactive.ExtendedTask,
    source_name_dict: dict,
    logger: Logger,
) -> reactive.calc:
    """
    This function produces the reactive/render functions necessary to producing the
    binding and perturbation response `source_name` upset plots. All arguments must be
    passed as keyword arguments.

    :param metadata_result_calc: This is the result from a reactive.extended_task,
        which may be run in the background. Result can be retrieved with .result()
    :param source_name_dict: A dictionary where the keys are the levels of
        `source_name` and the values are (possibly -- could be one to one) renamed
        factor levels for display
    :param logger: A logger object

    :return: A reactive.calc with the metadata filtered for the selected upset plot
        sets

    """

    selected_sets = reactive.Value(set())

    @reactive.calc
    def regulators_by_source_dict():
        df = metadata_result.result()
        df_filtered = df[df["source_name"].isin(source_name_dict.keys())]
        if df_filtered.empty:
            logger.warning(f"No data available for {session.ns('upset_plot')}.")
            return {}

        grouped = (
            df_filtered.groupby("source_name")["regulator_symbol"].apply(list).to_dict()
        )
        renamed = {source_name_dict.get(k, k): v for k, v in grouped.items()}
        return renamed

    @reactive.calc
    def selected_set_df():
        selected = selected_sets.get()
        if selected:
            keys = [k for k, v in source_name_dict.items() if v in selected]
            df = metadata_result.result()
            return df[df["source_name"].isin(keys)]
        return pd.DataFrame()

    @output
    @render_widget
    def upset_plot():
        req(regulators_by_source_dict())
        logger.info(f"Rendering UpSetJSWidget for {session.ns('upset_plot')}")
        source_dict = regulators_by_source_dict()

        w = UpSetJSWidget[str]()
        w.from_dict(source_dict, order_by="name")
        w.generate_intersections(order_by="degree", min_degree=2, empty=True)
        w.mode = "click"
        w.title = ""
        w.description = ""
        w.width = "100%"
        w.height = "100%"

        def selection_changed(s):
            sets = (
                {re.sub(r"[()]", "", x.strip()) for x in s.name.split("∩")}
                if s
                else set()
            )
            logger.info(f"{session.ns('upset_plot')} selection changed: {sets}")
            selected_sets.set(sets)

        w.on_selection_changed(selection_changed)
        return w

    return selected_set_df
