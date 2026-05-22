"""Splash page shown on initial load."""

from shiny import ui


def _feature_card(title: str, description: str, img_src: str | None = None) -> ui.Tag:
    """
    Feature card for the home page grid using Bootstrap card classes.

    :param title: Card heading.
    :param description: Short description text below the title.
    :param img_src: Optional path to an image shown at the left of the card body.

    """
    body_children: list[ui.Tag] = []
    if img_src is not None:
        body_children.append(
            ui.img(
                {
                    "src": img_src,
                    "style": "width:64px; height:64px; object-fit:contain;"
                    " flex-shrink:0; margin-right:1rem;",
                }
            )
        )
    body_children += [
        ui.div(
            ui.div({"class": "fw-bold fs-5 mb-1"}, title),
            ui.div(description),
        )
    ]
    return ui.div(
        {"class": "card mb-3"},
        ui.div(
            {
                "class": "card-body d-flex align-items-center",
            },
            *body_children,
        ),
    )


def home_ui() -> ui.Tag:
    return ui.div(
        {"class": "p-4"},
        ui.div(
            {"class": "alert alert-warning", "role": "alert"},
            ui.strong("Under development: "),
            "excuse the mess. Projected release: April, 2026.",
        ),
        ui.h2("Welcome to the TF Binding and Perturbation Explorer"),
        ui.p(
            "Explore datasets of transcription factor (TF) binding and gene "
            "expression responses following TF perturbation. Compare growth "
            "conditions, experimental techniques, or analytic techniques. "
            "Currently, all datasets are for ",
            ui.em("Saccharomyces cerevisiae"),
            " (yeast).",
        ),
        ui.h3("Getting Started"),
        ui.p(
            "Use the tabs above to navigate between pages. "
            "Start with Dataset selection to choose which datasets to analyse."
        ),
        ui.div(
            {"class": "mt-3"},
            _feature_card(
                "Dataset selection",
                "Begin here to choose and filter the datasets you want to "
                "analyse, then navigate to the other tabs to explore the results.",
            ),
            _feature_card(
                "Binding",
                "Compare TF binding targets in the selected binding datasets.",
                img_src="binding.png",
            ),
            _feature_card(
                "Perturbation",
                "Compare transcriptional responses to TF perturbations in "
                "the selected perturbation datasets.",
                img_src="perturbation.png",
            ),
            _feature_card(
                "Comparison",
                "Compare selected binding datasets to selected perturbation datasets.",
            ),
        ),
    )
