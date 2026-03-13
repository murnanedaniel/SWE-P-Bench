from decaylanguage import DecFileParser
from decaylanguage.dec.dec import get_model_name

def _extract_params(details):
    # details[3] may be a list of numbers or a string
    params = details[3]
    if isinstance(params, (list, tuple)):
        return [float(x) for x in params]
    if isinstance(params, str):
        s = params.strip()
        if not s:
            return []
        return [float(x) for x in s.split()]
    # fallback
    return []

def _first_decay_details(dec_string):
    dfp = DecFileParser.from_string(dec_string)
    dfp.parse()
    dms = dfp._find_decay_modes('B0sig')
    assert dms, "no decay modes found"
    dm = dms[0]
    details = dfp._decay_mode_details(dm, True)
    return dm, details

def test_oracle_001():
    # ISGW2 model should be recognized as "ISGW2" and not produce a leading "2" parameter
    s = """Decay B0sig
0.0030  MyD_0*- mu+ nu_mu       PHOTOS ISGW2;
Enddecay
"""
    dm, details = _first_decay_details(s)
    assert get_model_name(dm) == "ISGW2"
    assert _extract_params(details) == []

def test_oracle_002():
    # HQET2 with numeric parameters: the model name must be "HQET2" and parameters should not include the trailing "2"
    s = """Decay B0sig
0.0493  MyD*-   mu+ nu_mu       HQET2 1.207 0.908 1.406 0.853;
Enddecay
"""
    dm, details = _first_decay_details(s)
    assert get_model_name(dm) == "HQET2"
    assert _extract_params(details) == [1.207, 0.908, 1.406, 0.853]

def test_oracle_003():
    # ISGW2 with its own numeric parameters: ensure model is "ISGW2" and parameters parsed are exactly those provided
    s = """Decay B0sig
0.0100  D0   pi-       ISGW2 3.14 2.71;
Enddecay
"""
    dm, details = _first_decay_details(s)
    assert get_model_name(dm) == "ISGW2"
    assert _extract_params(details) == [3.14, 2.71]