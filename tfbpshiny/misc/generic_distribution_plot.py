import plotly.express as px

from ..utils.plot_formatter import format_distribution_plot
from ..utils.source_name_lookup import get_source_name_dict


def create_distribution_plot(
    df,
    y_column,
    y_axis_title,
    category_orders=None,
):
    """
    Create a standardized distribution plot.

    Args:
        df: DataFrame with the plot data
        y_column: Column name to plot on y-axis
        y_axis_title: Title for the y-axis
        category_orders: Optional dict of category orders

    Returns:
        A formatted plotly figure

    """
    if df.empty or not {y_column, "expression_source", "binding_source"}.issubset(
        df.columns
    ):
        return px.scatter(title="No data to plot")

    # Process source names
    df = df.copy()

    # Map binding sources to display names
    if "binding_source" in df.columns:
        source_name_dict = get_source_name_dict("binding")
        df["binding_source"] = df["binding_source"].map(
            lambda x: source_name_dict.get(x, x)
        )

    # Map expression sources to display names
    if "expression_source" in df.columns:
        source_name_dict = get_source_name_dict("perturbation_response")
        df["expression_source"] = df["expression_source"].map(
            lambda x: source_name_dict.get(x, x)
        )

    # Default category orders if not provided
    if category_orders is None:
        category_orders = {
            "expression_source": ["Overexpression", "2014 TFKO", "2007 TFKO"]
        }

    # Create the plot
    fig = px.box(
        df,
        x="binding_source",
        y=y_column,
        color="binding_source",
        facet_col="expression_source",
        points="outliers",
        category_orders=category_orders,
    )

    return format_distribution_plot(fig, y_axis_title)
