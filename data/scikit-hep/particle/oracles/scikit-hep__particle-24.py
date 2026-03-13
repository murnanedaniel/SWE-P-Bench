import particle

def _pdgid_of(p):
    return getattr(p, "pdgid", getattr(p, "pid", None))

def _name_of(p):
    return getattr(p, "name", None) or getattr(p, "particle", None) or getattr(p, "symbol", None)

def test_oracle_001():
    # Gluon (PDG ID 21) was missing before the patch
    p = particle.Particle.from_pdgid(21)
    assert _pdgid_of(p) == 21
    assert _name_of(p) is not None and 'g' in _name_of(p)

def test_oracle_002():
    # Higgs (PDG ID 25) was missing before the patch
    p = particle.Particle.from_pdgid(25)
    assert _pdgid_of(p) == 25
    assert _name_of(p) is not None and 'H' in _name_of(p)

def test_oracle_003():
    # Lambda_c(2625) (PDG ID 104122) / Xi_c(2815) entries were missing before the patch.
    # Check one charm-strange baryon that was added: Xi_c(2815)^{+} PDG 104322
    p = particle.Particle.from_pdgid(104322)
    assert _pdgid_of(p) == 104322
    name = _name_of(p)
    assert name is not None and "Xi" in name and "2815" in name