import inspect
import particle


def test_oracle_001():
    doc = inspect.getdoc(particle.Particle)
    assert "charge\n    The particle charge, in units of the positron charge." in doc


def test_oracle_002():
    doc = inspect.getdoc(particle.Particle)
    assert "mass_lower\n    The lower uncertainty on the particle mass, in MeV." in doc
    assert "mass_upper\n    The upper uncertainty on the particle mass, in MeV." in doc
    assert "width_lower\n    The lower uncertainty on the particle decay width, in MeV." in doc
    assert "width_upper\n    The upper uncertainty on the particle decay width, in MeV." in doc


def test_oracle_003():
    doc = inspect.getdoc(particle.Particle)
    assert "anti_flag\n    The particle-antiparticle flag." in doc
    assert "A = B" in doc
    assert "A = F" in doc
    assert "A = blank" in doc