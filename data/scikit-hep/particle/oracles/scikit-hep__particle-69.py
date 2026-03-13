import pytest
from particle import Particle

def test_oracle_001():
    p = Particle.from_pdgid(12)
    assert p.pdgid == 12

def test_oracle_002():
    p = Particle.from_pdgid(14)
    assert p.pdgid == 14

def test_oracle_003():
    p = Particle.from_pdgid(16)
    assert p.pdgid == 16