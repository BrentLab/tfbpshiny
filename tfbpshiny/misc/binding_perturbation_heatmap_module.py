from logging import Logger
from typing import Literal

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from shiny import Inputs, Outputs, Session, module, reactive, render, ui
from shinywidgets import output_widget, render_widget

from ..utils.source_name_lookup import BindingSource, PerturbationSource


@module.ui
def heatmap_comparison_ui():
    return ui.div(
        ui.row(
            ui.column(
                8,
                ui.card(
                    ui.card_header(
                        ui.div(
                            ui.output_text("heatmap_title"),
                            style="font-weight: bold; font-size: 1.1em;",
                        )
                    ),
                    ui.card_body(
                        output_widget("comparison_heatmap"), style="height: 500px;"
                    ),
                    ui.card_footer(
                        ui.div(
                            ui.input_radio_buttons(
                                "comparison_type",
                                label="Comparison Type:",
                                choices={
                                    "regulators": "Number of Common Regulators",
                                    "correlation": "Median Rank Correlation",
                                },
                                selected="regulators",
                                inline=True,
                            ),
                            ui.p(
                                "Click on any cell to see detailed information. "
                                "Diagonal cells show single dataset statistics.",
                                style="margin: 5px 0 0 0; font-size: 0.9em; color:"
                                "#666;",
                            ),
                        )
                    ),
                ),
            ),
            ui.column(
                4,
                ui.card(
                    ui.card_header("Selection Details"),
                    ui.card_body(
                        ui.output_ui("selection_details"),
                        style="max-height: 500px; overflow-y: auto;",
                    ),
                ),
            ),
        )
    )


@module.server
def heatmap_comparison_server(
    input: Inputs,
    output: Outputs,
    session: Session,
    *,
    metadata_result: reactive.ExtendedTask,
    source_name_dict: dict[str, str],
    data_type: Literal["binding","perturbation"]
    correlation_data: pd.DataFrame | None = None,
    logger: Logger,
) -> reactive.Value:
    """
    Server for interactive heatmap comparisons between datasets.

    :param metadata_result: Reactive extended task with metadata
    :param source_name_dict: Dictionary mapping source names to display names
    :param data_type: Type of data ("binding" or "perturbation_response")
    :param correlation_data: DataFrame with correlation data for correlation comparisons
    :param logger: Logger object
    :return: Reactive value with selected cell information

    """

    # Store selected cell information
    selected_cell = reactive.Value(None)

    @reactive.calc
    def processed_metadata():
        """Process metadata and organize by source."""
        df = metadata_result.result()
        if df.empty:
            return {}

        # Filter for sources in our dict
        df_filtered = df[df["source_name"].isin(source_name_dict.keys())]

        # Group regulators by source
        source_regulators = {}
        for source, display_name in source_name_dict.items():
            source_data = df_filtered[df_filtered["source_name"] == source]
            regulators = set(source_data["regulator_symbol"].unique())
            source_regulators[display_name] = regulators

        return source_regulators

    @reactive.calc
    def comparison_matrix():
        """Create comparison matrix based on selected type."""
        source_regulators = processed_metadata()
        comparison_type = input.comparison_type()

        if not source_regulators:
            return pd.DataFrame()

        # Define explicit order for sources dynamically from enums
        # This controls both row order (top to bottom) and column order (left to right)
        if data_type == "binding":
            desired_order = [source.value for source in BindingSource]
        elif data_type == "perturbation_response":
            desired_order = [source.value for source in PerturbationSource]
        else:
            desired_order = []  # Fallback to alphabetical if unknown data type

        # Filter to only include sources that exist in the data and match desired order
        sources = [source for source in desired_order if source in source_regulators]

        # Add any remaining sources not in the desired order (as fallback)
        remaining_sources = [
            source for source in source_regulators.keys() if source not in sources
        ]
        sources.extend(sorted(remaining_sources))

        n_sources = len(sources)

        # Initialize matrix
        matrix = np.zeros((n_sources, n_sources))

        if comparison_type == "regulators":
            # Fill with regulator overlap counts
            for i, source1 in enumerate(sources):
                for j, source2 in enumerate(sources):
                    if i == j:
                        # Diagonal: total regulators in single dataset
                        matrix[i, j] = len(source_regulators[source1])
                    elif i > j:
                        # Off-diagonal: common regulators (lower triangular)
                        common = len(
                            source_regulators[source1] & source_regulators[source2]
                        )
                        matrix[i, j] = common
                    else:
                        matrix[i, j] = np.nan

        elif comparison_type == "correlation" and correlation_data is not None:
            # Fill with correlation data
            for i, source1 in enumerate(sources):
                for j, source2 in enumerate(sources):
                    if i == j:
                        # Diagonal: perfect self-correlation
                        matrix[i, j] = 1.0
                    elif i > j:
                        # Off-diagonal: median correlation between datasets
                        corr_val = calculate_median_correlation(
                            source1, source2, source_regulators, correlation_data
                        )
                        matrix[i, j] = corr_val
                    else:
                        matrix[i, j] = np.nan

        # Convert to DataFrame with explicit ordering
        # index controls row order (top to bottom)
        # columns controls column order (left to right)
        df = pd.DataFrame(matrix, index=sources, columns=sources)

        return df

    def calculate_median_correlation(
        source1: str, source2: str, source_regulators: dict, corr_data: pd.DataFrame
    ) -> float:
        """Calculate median correlation between two sources."""
        common_regulators = source_regulators[source1] & source_regulators[source2]

        if len(common_regulators) == 0 or corr_data is None:
            return 0.0

        # This is a placeholder - you'll need to implement based on your correlation
        # data structure
        # The correlation_data should contain pairwise correlations between
        # regulators across sources
        correlations: list[float] = []
        for regulator in common_regulators:
            # Extract correlation for this regulator between the two sources
            # This depends on how your correlation data is structured
            pass

        return np.median(correlations) if correlations else 0.0

    @reactive.calc
    def heatmap_title_text():
        """Generate title based on comparison type."""
        comp_type = input.comparison_type()
        data_name = data_type.replace("_", " ").title()

        if comp_type == "regulators":
            return f"{data_name} Dataset Overlap: Number of Common Regulators"
        else:
            return f"{data_name} Dataset Correlation: Median Rank Correlations"

    @output
    @render.text
    def heatmap_title():
        return heatmap_title_text()

    @output(id="comparison_heatmap")
    @render_widget
    def comparison_heatmap():
        matrix_df = comparison_matrix()

        if matrix_df.empty:
            return px.scatter(title="No data available")

        # Create mask for lower triangular + diagonal
        mask = np.triu(np.ones_like(matrix_df.values, dtype=bool), k=1)
        matrix_masked = matrix_df.values.copy()
        matrix_masked[mask] = np.nan

        # Convert to Python list and replace np.nan with None for JSON compliance
        matrix_list: list[list[float | None]] = []
        text_list: list[list[str]] = []
        for row in matrix_masked:
            matrix_row: list[float | None] = []
            text_row = []
            for val in row:
                if np.isnan(val):
                    matrix_row.append(None)
                    text_row.append("")
                else:
                    matrix_row.append(val)
                    if input.comparison_type() == "regulators":
                        text_row.append(f"{int(val)}")
                    else:
                        text_row.append(f"{val:.2f}")
            matrix_list.append(matrix_row)
            text_list.append(text_row)

        # Create overlay of scatter points for click events - DEFINE VARIABLES FIRST
        x_vals = []
        y_vals = []
        cell_data = []  # Store cell metadata for click handling

        for i, y in enumerate(matrix_df.index):
            for j, x in enumerate(matrix_df.columns):
                if matrix_list[i][j] is not None:  # Only add points for non-None cells
                    x_vals.append(x)
                    y_vals.append(y)
                    cell_data.append(
                        {
                            "x": x,
                            "y": y,
                            "value": matrix_list[i][j],
                            "row_idx": i,
                            "col_idx": j,
                        }
                    )

        # Create the scatter trace FIRST (now that variables are defined)
        scatter = go.Scatter(
            x=x_vals,
            y=y_vals,
            mode="markers",
            marker=dict(
                opacity=0.8,  # Highly visible
                size=40,  # Medium size, easy to see
                color="red",  # Bright red for contrast
                symbol="circle",  # Circle shape
                line=dict(width=2, color="darkred"),
            ),
            showlegend=True,  # Show in legend for now
            hoverinfo="text",  # Show hover info
            hovertext=[
                f"Cell: {cell['x']} vs {cell['y']}<br>Value: {cell['value']}"
                for cell in cell_data
            ],
            name="Click Points (DEBUG)",
        )

        # Create the heatmap SECOND
        heatmap = go.Heatmap(
            z=matrix_list,
            x=matrix_df.columns.tolist(),
            y=matrix_df.index.tolist(),
            colorscale="Blues",
            showscale=True,
            hoverongaps=False,
            text=text_list,
            texttemplate="%{text}",
            textfont={"size": 12},
            hovertemplate="%{y} vs %{x}<br>Value: %{z}<br><i>Click to "
            "select</i><extra></extra>",
            connectgaps=False,
            customdata=matrix_df.columns.tolist(),
        )

        # Add them in order: scatter first (bottom), heatmap second (top)
        fig = go.Figure()

        fig.add_trace(scatter)  # Index 0
        fig.add_trace(heatmap)  # Index 1
        # Update layout
        fig.update_layout(
            xaxis_title="Dataset",
            yaxis_title="Dataset",
            height=450,
            margin=dict(l=100, r=50, t=50, b=100),
            xaxis=dict(
                tickangle=45,
                side="bottom",
                autorange=True,
                fixedrange=True,  # Disable zoom to prevent conflicts with clicks
            ),
            yaxis=dict(
                autorange="reversed",  # This ensures rows go top to bottom correctly
                fixedrange=True,  # Disable zoom to prevent conflicts with clicks
            ),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="white",
            showlegend=True,  # Show legend to see the debug trace
        )

        # Enable click events for plotly widget - disable pan/zoom to prevent conflicts
        fig.update_layout(
            clickmode="event",
            dragmode=False,  # Disable pan/zoom to allow clicking
            uirevision="constant",  # Helps maintain UI state
        )

        # Convert to FigureWidget for interactive events
        widget = go.FigureWidget(fig.data, fig.layout)

        logger.info(f"Widget type: {type(widget)}")
        logger.info(f"Widget traces: {len(widget.data)}")
        logger.info(f"Created {len(x_vals)} clickable scatter points")

        def on_point_click(trace, points, state):
            logger.info("on_point_click fired!")
            logger.info(f"Points: {points}")

            if hasattr(points, "point_inds") and points.point_inds:
                point_idx = points.point_inds[0]
                logger.info(f"Clicked point index: {point_idx}")

                # Get cell data from our stored metadata
                if point_idx < len(cell_data):
                    cell = cell_data[point_idx]
                    logger.info(f"Cell data: {cell}")

                    selected_cell.set(
                        {
                            "x": cell["x"],
                            "y": cell["y"],
                            "value": cell["value"],
                            "comparison_type": input.comparison_type(),
                        }
                    )
                    logger.info(
                        f"Successfully updated selected_cell: {cell['x']} vs "
                        f"{cell['y']}"
                    )
                else:
                    logger.error(
                        f"Point index {point_idx} out of range for cell_data "
                        f"(len={len(cell_data)})"
                    )
            else:
                logger.warning("No point_inds found in points object")

        def on_point_hover(trace, points, state):
            logger.info("on_point_HOVER fired!")
            logger.info(f"Hover Points: {points}")

        # Register both click and hover handlers on scatter (index 1)
        widget.data[0].on_click(on_point_click)
        widget.data[0].on_hover(on_point_hover)

        logger.info("Attached both click and hover handlers to widget.data[1].")

        return widget

    @output
    @render.ui
    def selection_details():
        """Generate details panel content based on selection."""
        cell_info = selected_cell.get()
        logger.info(f"Selection details: {cell_info}")
        source_regulators = processed_metadata()

        if not cell_info:
            # Show all regulators when no selection
            all_regulators = set()
            for regs in source_regulators.values():
                all_regulators.update(regs)

            return ui.div(
                ui.h5("All Regulators"),
                ui.p(f"Total: {len(all_regulators)} regulators"),
                ui.div(
                    create_searchable_list(sorted(all_regulators)),
                    style="max-height: 300px; overflow-y: auto;",
                ),
            )

        x_source = cell_info["x"]
        y_source = cell_info["y"]
        value = cell_info["value"]
        comp_type = cell_info["comparison_type"]

        if x_source == y_source:
            # Diagonal cell - single dataset
            regulators = sorted(source_regulators[x_source])
            return ui.div(
                ui.h5(f"{x_source} Dataset"),
                ui.p(f"Total regulators: {len(regulators)}"),
                create_searchable_list(regulators),
            )
        else:
            # Off-diagonal cell - comparison
            common_regs = sorted(
                source_regulators[x_source] & source_regulators[y_source]
            )

            if comp_type == "regulators":
                return ui.div(
                    ui.h5(f"{y_source} ∩ {x_source}"),
                    ui.p(f"Common regulators: {len(common_regs)}"),
                    create_searchable_list(common_regs),
                )
            else:
                # For correlation, show histogram (placeholder)
                return ui.div(
                    ui.h5(f"Correlation: {y_source} vs {x_source}"),
                    ui.p(f"Median correlation: {value:.3f}"),
                    ui.p("Distribution histogram would go here"),
                    create_searchable_list(common_regs),
                )

    def create_searchable_list(items: list[str]) -> ui.Tag:
        """Create a searchable list of items."""
        if not items:
            return ui.p("No items to display")

        # For now, create a simple scrollable list
        # Could be enhanced with actual search functionality
        list_items = [ui.tags.li(item) for item in items]

        return ui.div(
            ui.tags.ul(*list_items, style="list-style-type: none; padding-left: 0;"),
            style="border: 1px solid #ddd; border-radius: 4px; padding: 10px; "
            "background-color: #f9f9f9;",
        )

    return selected_cell
