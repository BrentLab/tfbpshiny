def format_distribution_plot(fig, y_axis_title=None):
    """
    Apply consistent formatting to distribution plots.

    Args:
        fig: A plotly figure object
        y_axis_title: Optional title for the y-axis

    Returns:
        The formatted plotly figure

    """
    fig.update_layout(
        margin=dict(l=40, r=120, t=50, b=80),
        height=450,
        boxmode="group",
        legend=dict(
            orientation="v",
            yanchor="top",
            y=0.99,
            xanchor="right",
            x=1.3,
            bgcolor="rgba(255, 255, 255, 0.8)",
            bordercolor="rgba(0, 0, 0, 0.2)",
            borderwidth=1,
        ),
        autosize=True,
    )

    # Set y-axis title if provided
    if y_axis_title:
        fig.update_layout(yaxis_title=y_axis_title)

    # Better handling of facet labels
    fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))

    # Ensure axes don't get cut off
    fig.update_xaxes(automargin=True)
    fig.update_yaxes(automargin=True, matches=None)

    return fig
