from particle.particle import enums
import pytest

def test_oracle_001():
    # '-' should map to Parity.m (minus)
    assert enums.Parity_mapping['-'] == enums.Parity.m

def test_oracle_002():
    # empty parity string should map to unknown (Parity.u)
    assert enums.Parity_mapping[''] == enums.Parity.u

def test_oracle_003():
    # empty charge string should map to unknown (Charge.u)
    assert enums.Charge_mapping[''] == enums.Charge.u