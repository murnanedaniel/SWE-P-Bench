import warnings
from decaylanguage.dec.dec import DecFileParser, get_decays

def test_oracle_001():
    # Verify that a CopyDecay statement is recognized and recorded
    decfile = """\
Decay B0
1.0 D0 pi- PHOTOS PHSP;
End
CopyDecay B0_copy B0
"""
    dfp = DecFileParser.from_string(decfile)
    dfp.parse()
    # The parser should record the mapping requested by CopyDecay
    assert dfp.dict_decays2copy() == {"B0_copy": "B0"}

def test_oracle_002():
    # Verify that the requested copy results in an actual copied Decay tree
    decfile = """\
Decay B0
1.0 D0 pi- PHOTOS PHSP;
End
CopyDecay B0_copy B0
"""
    dfp = DecFileParser.from_string(decfile)
    dfp.parse()
    # get_decays expects the parsed file tree; extract mother names from decay trees
    trees = get_decays(dfp._parsed_dec_file)
    names = {t.children[0].children[0].value for t in trees}
    # Both original and copied decay names must be present
    assert "B0" in names
    assert "B0_copy" in names

def test_oracle_003():
    # If CopyDecay references a non-existent decay, parser should warn and not add the copy
    decfile = """\
Decay B0
1.0 D0 pi- PHOTOS PHSP;
End
CopyDecay X_missing Y_nonexistent
"""
    dfp = DecFileParser.from_string(decfile)
    with warnings.catch_warnings(record=True) as rec:
        warnings.simplefilter("always")
        dfp.parse()
    # Mapping should still record the requested copy
    assert dfp.dict_decays2copy() == {"X_missing": "Y_nonexistent"}
    # But since the referenced decay does not exist, the actual copy should NOT be present
    trees = get_decays(dfp._parsed_dec_file)
    names = {t.children[0].children[0].value for t in trees}
    assert "X_missing" not in names
    # And a warning about missing corresponding Decay should have been issued
    assert any("CopyDecay" in str(w.message) or "CopyDecay" in str(w) for w in rec)