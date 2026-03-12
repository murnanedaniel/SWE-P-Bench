from particle import Particle, Inv

def test_oracle_001():
    # anti_flag attribute must exist and bar property should reflect antiparticle for negative pdgid
    p = Particle(-11, "e-", 0.511, 0.0, Inv.Full)
    assert getattr(p, "anti_flag") is Inv.Full
    assert p.bar is True

def test_oracle_002():
    # invert() must return the antiparticle (pdgid sign flipped) when anti_flag == Inv.Full
    p = Particle(11, "e+", 0.511, 0.0, Inv.Full)
    inv = p.invert()
    assert int(inv.pdgid) == -11 or inv.pdgid == -11

def test_oracle_003():
    # __str__ should include the tilde for inverted particle names when anti_flag == Inv.Full and pdgid < 0
    p = Particle(-11, "e-", 0.511, 0.0, Inv.Full)
    s = str(p)
    assert "~" in s