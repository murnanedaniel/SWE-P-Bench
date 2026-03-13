from particle import Particle


def test_oracle_001():
    p = Particle.from_string("a(2)(1320)+")
    assert p.name == "a(2)(1320)+"
    assert p.pdgid == 215


def test_oracle_002():
    p = Particle.from_string("f(2)(1270)")
    assert p.name == "f(2)(1270)"
    assert p.pdgid == 225


def test_oracle_003():
    p = Particle.from_string("K(2)*(1430)+")
    assert p.name == "K(2)*(1430)+"
    assert p.pdgid == 325