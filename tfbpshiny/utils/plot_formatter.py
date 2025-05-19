"""Utility functions for consistent plot formatting across the application."""


def plotly_plot_theme(plot_type=None):
    """
    Create a consistent theme dictionary for plotly plots.

    Args:
        plot_type: Optional string indicating plot type for specialized theming
                   (e.g., 'box', 'scatter', 'bar')

    Returns:
        Dictionary of theme settings to apply to plotly plots

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

    # Add specialized settings based on plot type
    if plot_type == "box":
        base_theme.update(
            {
                "boxmode": "group",
            }
        )
    elif plot_type == "scatter":
        base_theme.update(
            {
                # Scatter-specific settings
            }
        )
    elif plot_type == "bar":
        base_theme.update(
            {
                # Bar-specific settings
            }
        )

    return base_theme


def apply_plot_formatting(fig, plot_type=None, y_axis_title=None):
    """
    Apply consistent formatting to a plotly figure.

    Args:
        fig: A plotly figure object
        plot_type: Optional string indicating plot type (e.g., 'box', 'scatter', 'bar')
        y_axis_title: Optional title for the y-axis

    Returns:
        The formatted plotly figure

    """
    # Apply theme based on plot type
    theme = plotly_plot_theme(plot_type)
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


# Keep the original function for backward compatibility
def format_distribution_plot(fig, y_axis_title=None):
    """
    Apply consistent formatting to distribution plots.

    Args:
        fig: A plotly figure object
        y_axis_title: Optional title for the y-axis

    Returns:
        The formatted plotly figure

    """
    return apply_plot_formatting(fig, plot_type="box", y_axis_title=y_axis_title)
