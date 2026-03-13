from particle import Particle

def test_oracle_001():
    # repr should put name first, then pdgid
    p = Particle.from_pdgid(5122)  # Lambda(b)0
    r = repr(p)
    assert r.startswith("<Particle:")
    # New behavior: name comes before pdgid in repr
    assert "name='Lambda(b)0', pdgid=5122" in r

def test_oracle_002():
    # describe() should start with "Name: ..." line (not "PDG name:")
    p = Particle.from_pdgid(311)  # K0
    desc = p.describe()
    first_line = desc.splitlines()[0]
    assert first_line.startswith("Name:")
    # Ensure old "PDG name:" is not present anywhere
    assert "PDG name:" not in desc

def test_oracle_003():
    # describe() should format antiparticle name before the status
    p = Particle.from_pdgid(311)  # K0 has antiparticle K~0 with Full status
    desc = p.describe()
    assert "Antiparticle name: K~0 (antiparticle status: Full)" in desc