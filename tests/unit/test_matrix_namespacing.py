"""Unit tests: matrix cell buttons emit namespaced Shiny input ids.

The matrix builders render plain ``<button>`` elements whose ``onclick`` calls
``Shiny.setInputValue(...)``. Because the cell-click effects run inside
``@module.server`` modules, the input id written by the client must be the
module-namespaced id (``{ns}-<id>``); a bare id writes to the root namespace and
never reaches the module effect. These tests pin that the builders apply the
provided namespace function to every cell button id.
"""

import pandas as pd

from tfbpshiny.utils.correlation_matrix import build_correlation_matrix_ui
from tfbpshiny.utils.topn_matrix import build_topn_matrix_ui


def _ns(prefix: str):
    return lambda s: f"{prefix}-{s}"


def test_corr_matrix_namespaces_button_ids():
    html = str(
        build_correlation_matrix_ui(
            all_possible_pairs=[("a", "b")],
            active_pairs=[("a", "b")],
            active_datasets=["a", "b"],
            corr_data={("a", "b"): pd.DataFrame({"correlation": [0.5]})},
            display_names={"a": "A", "b": "B"},
            selected_pairs=set(),
            ns=_ns("binding"),
        )
    )
    # str(tag) HTML-escapes the onclick single quotes to &apos;.
    assert "setInputValue(&apos;binding-corrpair_a__b&apos;" in html
    # The bare (root-namespace) id must not appear — it would never reach the
    # module-scoped click effect.
    assert "setInputValue(&apos;corrpair_a__b&apos;" not in html


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
    # Without an explicit ns (e.g. standalone page_test usage), ids are bare.
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
