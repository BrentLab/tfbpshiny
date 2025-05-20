from plotly.graph_objects import Figure


def plot_formatter() -> dict:
    """
    Create a consistent theme dictionary for plotly plots.

    :return: Dictionary of theme settings to apply to plotly plots
    """
    # Base theme applied to all plots
    base_theme = {
        "margin": dict(l=40, r=120, t=50, b=80),
        "height": 450,
        "autosize": True,
        "legend": dict(
            orientation="v",
            yanchor="top",
            y=0.99,
            xanchor="right",
            x=1.3,
            bgcolor="rgba(255, 255, 255, 0.8)",
            bordercolor="rgba(0, 0, 0, 0.2)",
            borderwidth=1,
        ),
    }

    return base_theme


def apply_plot_formatter(
    fig: Figure,
    y_axis_title: str | None = None,
) -> Figure:
    """
    Apply consistent formatting to a plotly figure.

    :param fig: A plotly figure object
    :param y_axis_title: A y axis title (optional)
    :return: A plotly figure object with consistent formatting applied
    :raises ValueError: If fig is not a plotly figure or if y_axis_title is not a string

    """
    if not isinstance(fig, Figure):
        raise ValueError("fig must be a plotly.graph_objs.Figure object")
    if y_axis_title and not isinstance(y_axis_title, str):
        raise ValueError("y_axis_title must be a string or None")

    # Apply theme based on plot type
    theme = plot_formatter()
    fig.update_layout(**theme)

    # Set y-axis title if provided
    if y_axis_title:
        fig.update_layout(yaxis_title=y_axis_title)

    # Better handling of facet labels
    fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))

    # Ensure axes don't get cut off
    fig.update_xaxes(automargin=True)
    fig.update_yaxes(automargin=True, matches=None)

    return fig
