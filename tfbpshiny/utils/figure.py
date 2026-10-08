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

#: Colour cycle for figures that plot *pairs* of datasets (figure 6's overlap
#: agreement) rather than one dataset per series. Deliberately avoids every hue family
#: already claimed by the dataset colours (the registry's ``color`` column: purple,
#: red-orange, teal,
#: light blue, navy, salmon, mint) -- reusing those, even approximately, risks a reader
#: mistaking a pair's colour for one specific dataset's, since a pair isn't "the
#: dataset that happens to be tinted red" the way a single-series figure's line is. An
#: earlier version of this palette (ColorBrewer Dark2) still clashed: its teal and
#: purple-blue read as near-duplicates of the ChEC-seq and ChIP-chip dataset colours. A
#: later revision of *this* palette paired an olive and a true green that, despite
#: being 40 degrees apart on the wheel, still read as "both green" at line/marker
#: sizes -- replaced with a plain blue, the one common hue family the rest of this
#: palette hadn't used yet.
#: Cycles if more than 8 pairs are selected; figure 6 already warns above
#: AGREEMENT_PAIR_WARN pairs that the plot becomes hard to read regardless.
PAIR_COLORS: tuple[str, ...] = (
    "#C9A227",
    "#1F77B4",
    "#2CA02C",
    "#C2185B",
    "#8B0000",
    "#8B5A2B",
    "#5A5A5A",
    "#222222",
)


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
    # Text defaults to plotly's own dark blue-grey, not true black -- set every font
    # color explicitly rather than rely on that or on inheritance from `layout.font`,
    # since a more specific font dict (e.g. an axis's own `tickfont`) does not
    # reliably pick up an unset color from a less specific one.
    fig.update_layout(
        font=dict(size=FONT_SIZE, color="black"),
        title=(
            dict(text=title, font=dict(size=TITLE_SIZE, color="black"))
            if title is not None
            else None
        ),
        showlegend=showlegend,
        legend=dict(font=dict(size=FONT_SIZE, color="black")),
        margin=dict(l=70, r=30, t=60 if title else 30, b=60),
        plot_bgcolor="white",
        height=height,
    )
    axis_kwargs: dict[str, Any] = dict(
        title_font=dict(size=AXIS_TITLE_SIZE, color="black"),
        tickfont=dict(size=FONT_SIZE, color="black"),
        showline=True,
        linecolor="#444",
    )
    # Vertical guide lines (x-axis gridlines) are dropped across every figure: with
    # several series per panel they add visual clutter without carrying information
    # the axis ticks don't already give. Horizontal gridlines (y-axis) are kept --
    # they help read a value off a shared scale across panels.
    fig.update_xaxes(**axis_kwargs, showgrid=False)
    fig.update_yaxes(**axis_kwargs, gridcolor="#eee")
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
        font=dict(size=FONT_SIZE - 2, color="black"),
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
    "FONT_SIZE",
    "PAIR_COLORS",
    "TITLE_SIZE",
    "apply_figure_style",
    "figure_html",
    "inside_legend",
    "matplotlib_svg_html",
]
