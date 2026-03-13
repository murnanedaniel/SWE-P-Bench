import pytest
from decaylanguage.dec.dec import DecFileParser


def test_oracle_001():
    parser = DecFileParser.from_string("JetSetPar MSTJ(26)=0\n")
    parsed = parser.parse()
    assert parsed is not None


def test_oracle_002():
    decfile = """Decay eta_c
0.000580 K_S0 K_S0 SSS_CP beta dm -1 1 0 1 0.0;
Enddecay
"""
    parser = DecFileParser.from_string(decfile)
    parsed = parser.parse()
    assert parsed is not None


def test_oracle_003():
    decfile = """JetSetPar MSTJ(26)=0
JetSetPar PARJ(21)=0.36
"""
    parser = DecFileParser.from_string(decfile)
    parser.parse()
    assert parser.dict_jetset_definitions() == {"MSTJ": {26: 0.0}, "PARJ": {21: 0.36}}