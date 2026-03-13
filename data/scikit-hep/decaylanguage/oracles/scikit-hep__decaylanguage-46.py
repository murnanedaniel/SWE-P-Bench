import tempfile

from decaylanguage.dec.dec import DaughtersDict, DecFileParser, get_model_parameters


def _parse_single_decay(dec_text):
    with tempfile.NamedTemporaryFile("w", suffix=".dec", delete=False) as f:
        f.write(dec_text)
        path = f.name
    parser = DecFileParser(path)
    parser.parse()
    decays = parser.list_decay_modes("MyP", pdg_name=False)
    assert len(decays) == 1
    return decays[0]


def test_oracle_001_define_replaces_model_parameter_variable():
    decay = _parse_single_decay(
        """
Define dm 0.507e12
Decay MyP
1.0 A B VSS_BMIX dm;
Enddecay
"""
    )
    assert get_model_parameters(decay) == [0.507e12]


def test_oracle_002_defined_and_numeric_model_parameters_are_all_returned_with_values():
    decay = _parse_single_decay(
        """
Define x 1.25
Decay MyP
1.0 A B SVV_HELAMP x 2.5;
Enddecay
"""
    )
    assert get_model_parameters(decay) == [1.25, 2.5]


def test_oracle_003_undefined_label_model_parameter_is_preserved():
    decay = _parse_single_decay(
        """
Decay MyP
1.0 A B LbAmpGen DtoKpipipi_v1;
Enddecay
"""
    )
    assert get_model_parameters(decay) == ["DtoKpipipi_v1"]