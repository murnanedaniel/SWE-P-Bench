import pyhf


def test_oracle_001():
    assert pyhf.exceptions.InvalidModifier.__doc__ is not None
    assert "creating a custom modifier with the wrong structure" in pyhf.exceptions.InvalidModifier.__doc__
    assert "initializing a modifier that does not exist, or has not been loaded" in pyhf.exceptions.InvalidModifier.__doc__


def test_oracle_002():
    assert pyhf.exceptions.InvalidInterpCode.__doc__ is not None
    assert "invalid/unimplemented interpolation code" in pyhf.exceptions.InvalidInterpCode.__doc__


def test_oracle_003():
    assert pyhf.modifiers.__all__ == [
        "histosys",
        "normfactor",
        "normsys",
        "shapefactor",
        "shapesys",
        "staterror",
    ]