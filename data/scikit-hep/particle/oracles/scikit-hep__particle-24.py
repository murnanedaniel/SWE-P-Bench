from particle import Particle


def test_oracle_001():
    p = Particle.from_pdgid(21)
    assert p.pdgid == 21
    assert p.name == "g"


def test_oracle_002():
    p = Particle.from_pdgid(25)
    assert p.pdgid == 25
    assert p.name == "H"


def test_oracle_003():
    p = Particle.from_pdgid(1000223)
    assert p.pdgid == 1000223
    assert p.name == "omega(1420)"