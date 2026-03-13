from particle.particle.particle import Particle

def test_oracle_001():
    # The enhanced documentation should mention the particle charge and its units.
    assert "The particle charge, in units of the positron charge." in (Particle.__doc__ or "")

def test_oracle_002():
    # The enhanced documentation should mention the particle mass and units (MeV).
    assert "The particle mass, in MeV." in (Particle.__doc__ or "")

def test_oracle_003():
    # The enhanced documentation should include the particle-antiparticle flag description.
    assert "The particle-antiparticle flag." in (Particle.__doc__ or "")