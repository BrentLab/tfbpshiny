"""
Shared plotly helpers for publication-oriented figures.

Every figure in the Figures module goes through :func:`apply_figure_style` so the
typography and margins stay consistent, and through :func:`figure_html` so plotly.js
is never re-fetched.

"""

from __future__ import annotations

import base64
import io
from typing import Any

import plotly.graph_objects as go
from plotly.io import to_html
from shiny import ui

#: Base font size. Deliberately large -- these figures are meant to be readable when
#: dropped into a slide or a manuscript, not just on a wide monitor.
FONT_SIZE = 16
AXIS_TITLE_SIZE = 18
TITLE_SIZE = 20

#: Colour per binding dataset, keyed by ``dataset_registry.base_label``. Extends the
#: npg-style pair already used for binding methods in
#: ``modules/comparison/queries.py``.
BINDING_COLORS: dict[str, str] = {
    "2004 ChIP-chip": "#7B4F9E",
    "2021 ChIP-exo": "#E64B35",
    "2025 ChEC-seq": "#00A087",
    "2026 Calling Cards": "#4DBBD5",
}

#: Colour per perturbation dataset, keyed by ``base_label``.
PERTURBATION_COLORS: dict[str, str] = {
    "2014 TFKO": "#3C5488",
    "2020 Overexpression": "#F39B7F",
    "2025 Degron": "#91D1C2",
}


def apply_figure_style(
    fig: go.Figure,
    *,
    title: str | None = None,
    x_title: str | None = None,
    y_title: str | None = None,
    height: int | None = None,
    showlegend: bool = True,
) -> go.Figure:
    """
    Apply the shared publication styling to a figure, in place.

    :param fig: Figure to style.
    :param title: Optional figure title.
    :param x_title: Optional x-axis title.
    :param y_title: Optional y-axis title.
    :param height: Optional pixel height.
    :param showlegend: Whether to draw the legend.
    :returns: The same figure, for chaining.

    """
    fig.update_layout(
        font=dict(size=FONT_SIZE),
        title=(
            dict(text=title, font=dict(size=TITLE_SIZE)) if title is not None else None
        ),
        showlegend=showlegend,
        legend=dict(font=dict(size=FONT_SIZE)),
        margin=dict(l=70, r=30, t=60 if title else 30, b=60),
        plot_bgcolor="white",
        height=height,
    )
    axis_kwargs: dict[str, Any] = dict(
        title_font=dict(size=AXIS_TITLE_SIZE),
        tickfont=dict(size=FONT_SIZE),
        showline=True,
        linecolor="#444",
        gridcolor="#eee",
    )
    fig.update_xaxes(**axis_kwargs)
    fig.update_yaxes(**axis_kwargs)
    if x_title is not None:
        fig.update_xaxes(title_text=x_title)
    if y_title is not None:
        fig.update_yaxes(title_text=y_title)
    return fig


def inside_legend(
    *,
    x: float = 0.98,
    y: float = 0.98,
    xanchor: str = "right",
    yanchor: str = "top",
) -> dict[str, Any]:
    """
    Legend styling for placing the legend inside the plotting area.

    Frees the horizontal space an outside legend would take, which matters for figures
    that need every pixel of plot width. The translucent background keeps series
    visible if a line passes underneath.

    Defaults to the top-right corner, which is empty in both figures that use this:
    rank-response and overlap-enrichment curves both fall from left to right.

    :param x: Paper-coordinate x position.
    :param y: Paper-coordinate y position.
    :param xanchor: Which edge of the legend ``x`` refers to.
    :param yanchor: Which edge of the legend ``y`` refers to.
    :returns: A ``layout.legend`` dict.

    """
    return dict(
        x=x,
        y=y,
        xanchor=xanchor,
        yanchor=yanchor,
        bgcolor="rgba(255,255,255,0.82)",
        bordercolor="#bbb",
        borderwidth=1,
        font=dict(size=FONT_SIZE - 2),
    )


def figure_html(fig: go.Figure, *, filename: str | None = None) -> ui.HTML:
    """
    Render a plotly figure as embeddable HTML with an SVG download button.

    Uses ``include_plotlyjs=False`` because ``app.py`` already loads a bundled
    ``plotly-3.5.0.min.js`` from ``www/``. Passing ``"cdn"`` (as the binding and
    perturbation modules currently do) fetches a second, different plotly build over
    the network once per figure.

    Plotly's modebar camera button saves PNG by default, which is useless for a
    manuscript. ``toImageButtonOptions.format`` switches it to SVG, so the existing
    button becomes a vector export with no extra UI.

    :param fig: Figure to render.
    :param filename: Base name for the downloaded file, without extension.
    :returns: HTML fragment.

    """
    config: dict[str, Any] = {
        "toImageButtonOptions": {
            "format": "svg",
            "filename": filename or "figure",
            "scale": 1,
        },
        "displaylogo": False,
        # Figures that omit an explicit layout width are sized by their container;
        # without this they render once at a default width and never reflow.
        "responsive": True,
    }
    return ui.HTML(to_html(fig, include_plotlyjs=False, full_html=False, config=config))


def matplotlib_svg_html(
    mpl_figure: Any, *, alt: str = "", filename: str | None = None
) -> ui.Tag:
    """
    Render a matplotlib figure as an inline SVG, with a download link, and close it.

    Used for the Venn diagrams, which have no plotly equivalent and so get none of
    plotly's modebar. SVG rather than PNG so the output is vector like every other
    figure on the page.

    Right-clicking a data-URI image gives inconsistent results across browsers and no
    sensible filename, so a ``download`` anchor is emitted alongside it. That is the
    counterpart of the SVG camera button :func:`figure_html` configures for plotly
    figures.

    :param mpl_figure: A ``matplotlib.figure.Figure``.
    :param alt: Alt text for the ``<img>``.
    :param filename: Base name for the download, without extension. When omitted no
        download link is drawn.
    :returns: A ``<div>`` holding the image and, when named, its download link.

    """
    buf = io.BytesIO()
    mpl_figure.savefig(buf, format="svg", bbox_inches="tight")
    buf.seek(0)
    encoded = base64.b64encode(buf.read()).decode("ascii")
    # Close explicitly: these figures are created per render.
    try:
        import matplotlib.pyplot as plt

        plt.close(mpl_figure)
    except Exception:  # noqa: BLE001 - closing is best-effort
        pass

    src = f"data:image/svg+xml;base64,{encoded}"
    img = ui.tags.img(src=src, alt=alt, style="max-width: 100%; height: auto;")
    if filename is None:
        return ui.div(img)
    return ui.div(
        img,
        ui.tags.a(
            "Download SVG",
            href=src,
            download=f"{filename}.svg",
            class_="btn btn-sm btn-outline-secondary",
            style="margin-top: 0.5rem;",
        ),
        style="display: flex; flex-direction: column; align-items: center;",
    )


__all__ = [
    "AXIS_TITLE_SIZE",
    "BINDING_COLORS",
    "FONT_SIZE",
    "PERTURBATION_COLORS",
    "TITLE_SIZE",
    "apply_figure_style",
    "figure_html",
    "inside_legend",
    "matplotlib_svg_html",
]
