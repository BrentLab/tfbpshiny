from logging import Logger

from shiny import Inputs, Outputs, Session, module, reactive, render, req, ui

from ..utils.rename_dataframe_data_sources import rename_dataframe_data_sources


@module.ui
def main_table_ui():
    return ui.output_data_frame("main_table")


@module.server
def main_table_server(
    input: Inputs,
    output: Outputs,
    session: Session,
    *,
    rr_metadata: reactive.calc,
    bindingmanualqc_result: reactive.ExtendedTask,
    logger: Logger,
) -> reactive.calc:
    """
    Main table server showing promotersetsig, binding_source, insert columns, and QC
    columns.

    :param rr_metadata: Complete rank response metadata
    :param bindingmanualqc_result: Binding manual QC data
    :param logger: Logger object
    :return: Reactive calc returning selected promotersetsigs

    """

    df_local_reactive = reactive.Value()

    @render.data_frame
    def main_table():
        req(rr_metadata)
        rr_df = rr_metadata().copy()  # type: ignore

        qc_df = bindingmanualqc_result.result()

        # Get unique combinations with insert columns
        main_df = rr_df[
            [
                "promotersetsig",
                "binding_source",
                "single_binding",
                "composite_binding",
                "genomic_inserts",
                "mito_inserts",
                "plasmid_inserts",
            ]
        ].drop_duplicates()

        # Merge with QC data
        if "rank_response_status" in qc_df.columns and "dto_status" in qc_df.columns:
            qc_subset = qc_df[
                [
                    "single_binding",
                    "composite_binding",
                    "rank_response_status",
                    "dto_status",
                ]
            ].drop_duplicates()
            main_df = main_df.merge(
                qc_subset, on=["single_binding", "composite_binding"], how="left"
            )

        # Reorder columns with promotersetsig first
        display_columns = [
            "promotersetsig",
            "binding_source",
            "genomic_inserts",
            "mito_inserts",
            "plasmid_inserts",
            "rank_response_status",
            "dto_status",
        ]
        existing_columns = [col for col in display_columns if col in main_df.columns]
        main_df = main_df[existing_columns]

        main_df = rename_dataframe_data_sources(main_df)
        main_df.reset_index(drop=True, inplace=True)

        df_local_reactive.set(main_df)

        return render.DataGrid(
            main_df,
            selection_mode="rows",
        )

    @reactive.calc
    def get_selected_promotersetsigs():
        req(df_local_reactive)
        selected_rows = main_table.cell_selection()["rows"]
        df_local = df_local_reactive.get()
        if not selected_rows or df_local.empty:
            return set()
        return set(df_local.loc[list(selected_rows), "promotersetsig"])

    return get_selected_promotersetsigs
