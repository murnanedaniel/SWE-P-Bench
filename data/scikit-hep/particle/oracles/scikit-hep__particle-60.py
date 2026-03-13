from particle import Particle
from particle.particle.enums import Parity


def test_oracle_001():
    p = Particle.from_pdgid(313)
    assert p.P == Parity.m


def test_oracle_002():
    p = Particle.from_pdgid(5122)
    assert p.P == Parity.p


def test_oracle_003():
    p = Particle.from_pdgid(22)
    assert p.P == Parity.m