from particle import Particle

def test_oracle_001():
    # Photon should not show a trailing "0" in fullname (was "gamma0" in buggy code)
    p = Particle.from_pdgid(22)
    assert p.fullname == 'gamma'

def test_oracle_002():
    # Proton fullname should be "p" (not "p+")
    p = Particle.from_pdgid(2212)
    assert p.fullname == 'p'

def test_oracle_003():
    # Programmatic name for pi0 should use "_0" (not "0" at end)
    p = Particle.from_pdgid(111)
    assert p.programmatic_name == 'pi_0'