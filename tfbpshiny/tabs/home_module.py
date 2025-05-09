from shiny import module, ui


@module.ui
def home_ui():
    return ui.div(
        ui.h2("Welcome to the TF Binding and Perturbation Explorer"),
        ui.p(
            "This application provides an interactive interface for exploring "
            "datasets of transcription factor (TF) binding and gene expression "
            "responses following TF perturbation in yeast."
        ),
        ui.h3("How to Use This App"),
        ui.p(
            "Navigate through the tabs above to interact "
            "with different visualizations:"
        ),
        ui.tags.ul(
            ui.tags.li(
                ui.strong("Binding: "),
                (
                    "View TF binding profiles across multiple datasets "
                    "using UpSet plots and correlation matrices."
                ),
            ),
            ui.tags.li(
                ui.strong("Perturbation Response: "),
                "Explore how TF knockouts or overexpression affect gene expression.",
            ),
            ui.tags.li(
                ui.strong("All Regulator Comparisons: "),
                (
                    "See a global overview of rank response and "
                    "DTO distributions across all regulators."
                ),
            ),
            ui.tags.li(
                ui.strong("Individual Regulator Comparisons: "),
                (
                    "Zoom in on specific regulators to examine "
                    "replicate-level perturbation effects."
                ),
            ),
        ),
        ui.h3("Getting Started"),
        ui.p(
            "Begin by selecting a tab to load a dataset and explore visual summaries "
            "of binding and expression response relationships."
        ),
        class_="home-content p-4",
    )
