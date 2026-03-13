from particle.particle.enums import Parity_mapping, Parity

def test_oracle_001():
    # '-' should map to Parity.m (minus)
    assert Parity_mapping['-'] == Parity.m

def test_oracle_002():
    # empty string should map to unknown parity (Parity.u)
    assert Parity_mapping[''] == Parity.u

def test_oracle_003():
    # the full expected mapping for parity characters
    expected = {
        '+': Parity.p,
        '0': Parity.o,
        '-': Parity.m,
        '?': Parity.u,
        '': Parity.u,
    }
    assert Parity_mapping == expected