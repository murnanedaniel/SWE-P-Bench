import pytest

from decaylanguage.dec.dec import find_charge_conjugate_match
from decaylanguage.decay.decay import charge_conjugate


def test_oracle_001():
    # Expect the library to find the charge-conjugate of a simple charged pion
    assert find_charge_conjugate_match("pi+") == "pi-"


def test_oracle_002():
    # The public charge_conjugate helper should invert a known particle name
    assert charge_conjugate("pi+") == "pi-"


def test_oracle_003():
    # For an unknown particle name, the function should return the generic ChargeConj(...) form
    unknown = "THIS_IS_NOT_A_PARTICLE"
    assert charge_conjugate(unknown) == f"ChargeConj({unknown})"