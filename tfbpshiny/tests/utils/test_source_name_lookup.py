import pytest

from tfbpshiny.utils.source_name_lookup import get_source_name_dict


def test_full_mapping_contains_expected_keys():
    d = get_source_name_dict()
    assert "harbison_chip" in d
    assert "mcisaac_oe" in d
    assert d["harbison_chip"] == "ChIP-chip"
    assert d["mcisaac_oe"] == "Overexpression"


def test_binding_only_mapping():
    d = get_source_name_dict(datatype="binding")
    assert "mcisaac_oe" not in d
    assert d["brent_nf_cc"] == "Calling Cards"


def test_perturbation_only_mapping():
    d = get_source_name_dict(datatype="perturbation_response")
    assert "mcisaac_oe" in d
    assert "harbison_chip" not in d


def test_reverse_full_mapping():
    d = get_source_name_dict(reverse=True)
    assert d["ChIP-chip"] == "harbison_chip"
    assert d["Overexpression"] == "mcisaac_oe"


def test_reverse_binding_only():
    d = get_source_name_dict(datatype="binding", reverse=True)
    assert d["Calling Cards"] == "brent_nf_cc"
    assert "Overexpression" not in d


def test_reverse_perturbation_only():
    d = get_source_name_dict(datatype="perturbation_response", reverse=True)
    assert d["2007 TFKO"] == "hu_reimann_tfko"
    assert "ChIP-chip" not in d


def test_invalid_datatype_raises():
    with pytest.raises(ValueError, match="Invalid datatype"):
        get_source_name_dict(datatype="nonsense")  # type: ignore
