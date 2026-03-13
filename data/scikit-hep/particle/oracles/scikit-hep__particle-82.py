from particle.particle.particle import Particle

def test_oracle_001():
    # Particle.empty() should provide a meaningful default latex_name
    p = Particle.empty()
    assert p.latex_name == 'Unknown'

def test_oracle_002():
    # Accessing .charge on an "empty" particle must not raise and should be None
    p = Particle.empty()
    assert p.charge is None

def test_oracle_003():
    # latex_name should not be an empty string for the empty particle
    p = Particle.empty()
    assert p.latex_name != ''