from plotly.graph_objects import Figure


def plot_formatter(
    fig: Figure,
    y_axis_title: str | None = None,
    show_legend: bool = True,
) -> Figure:
    if not isinstance(fig, Figure):
        raise ValueError("fig must be a plotly.graph_objs.Figure object")
    if y_axis_title and not isinstance(y_axis_title, str):
        raise ValueError("y_axis_title must be a string or None")

    # Apply global layout
    fig.update_layout(
        plot_bgcolor="white",
        paper_bgcolor="white",
        showlegend=show_legend,
        font=dict(family="Arial, sans-serif", size=12, color="#333"),
    )

    # Apply to all x- and y-axes (important for facet plots)
    fig.update_xaxes(
        showgrid=True,
        gridcolor="lightgray",
        showline=True,
        linecolor="black",
        linewidth=1,
        mirror=True,
        automargin=True,
    )
    fig.update_yaxes(
        showgrid=True,
        gridcolor="lightgray",
        showline=True,
        linecolor="black",
        linewidth=1,
        mirror=True,
        automargin=True,
    )

    # Optional y-axis title
    if y_axis_title:
        fig.update_yaxes(title=y_axis_title)

    # Simplify facet strip text
    # (e.g., "expression_source=Overexpression" to "Overexpression")
    fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))

    return fig
