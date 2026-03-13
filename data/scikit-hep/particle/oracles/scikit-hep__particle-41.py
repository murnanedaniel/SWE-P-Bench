from particle import Particle


def test_oracle_001():
    p = Particle.from_string("K(2)*(1430)0")
    assert p.pdgid == 315


def test_oracle_002():
    p = Particle.from_string("a(2)(1320)-")
    assert p.pdgid == -215


def test_oracle_003():
    p = Particle.from_string("rho(3)(1690)0")
    assert p.pdgid == 117