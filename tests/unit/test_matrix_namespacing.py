"""Unit tests: matrix cell buttons emit namespaced Shiny input ids.

The matrix builders render plain ``<button>`` elements whose ``onclick`` calls
``Shiny.setInputValue(...)``. Because the cell-click effects run inside
``@module.server`` modules, the input id written by the client must be the
module-namespaced id (``{ns}-<id>``); a bare id writes to the root namespace and
never reaches the module effect. These tests pin that the builders apply the
provided namespace function to every cell button id.

``build_correlation_matrix_ui`` is not covered here: it was made a read-only
display (no ``ns``, no ``selected_pairs``, no click behavior) in 2f96f57, and
``build_topn_matrix_ui`` is the only remaining clickable, namespaced matrix builder.
"""

from tfbpshiny.utils.topn_matrix import build_topn_matrix_ui


def _ns(prefix: str):
    return lambda s: f"{prefix}-{s}"


def test_topn_matrix_namespaces_button_ids():
    html = str(
        build_topn_matrix_ui(
            binding_datasets=["rossi"],
            perturbation_datasets=["kemmeren"],
            topn_medians={("rossi", "kemmeren"): 16.0},
            display_names={"rossi": "Rossi", "kemmeren": "Kemmeren"},
            selected_binding=None,
            selected_perturbation=None,
            ns=_ns("comparison"),
        )
    )
    assert "setInputValue(&apos;comparison-topncell_rossi__kemmeren&apos;" in html
    assert "setInputValue(&apos;comparison-topnrow_rossi&apos;" in html
    assert "setInputValue(&apos;comparison-topncol_kemmeren&apos;" in html
    assert "setInputValue(&apos;topncell_rossi__kemmeren&apos;" not in html


def test_matrix_builders_default_ns_is_identity():
    # Without an explicit ns, ids are bare.
    html = str(
        build_topn_matrix_ui(
            binding_datasets=["rossi"],
            perturbation_datasets=["kemmeren"],
            topn_medians={("rossi", "kemmeren"): 16.0},
            display_names={},
            selected_binding=None,
            selected_perturbation=None,
        )
    )
    assert "setInputValue(&apos;topncell_rossi__kemmeren&apos;" in html
