import inspect
from particle import Particle


def test_oracle_001():
    doc = inspect.getdoc(Particle)
    assert "charge\n    The particle charge, in units of the positron charge." in doc


def test_oracle_002():
    doc = inspect.getdoc(Particle)
    assert "mass_lower\n    The lower uncertainty on the particle mass, in MeV." in doc


def test_oracle_003():
    doc = inspect.getdoc(Particle)
    assert "anti_flag\n    The particle-antiparticle flag." in doc