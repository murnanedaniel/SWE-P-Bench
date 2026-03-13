from particle import Particle


def test_oracle_001():
    assert Particle.from_pdgid(22).fullname == "gamma"


def test_oracle_002():
    assert Particle.from_pdgid(2212).fullname == "p"


def test_oracle_003():
    assert Particle.from_pdgid(-2).fullname == "u~"