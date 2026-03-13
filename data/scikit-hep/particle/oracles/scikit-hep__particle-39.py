import math
import pytest

from particle.particle.kinematics import lifetime_to_width, width_to_lifetime
from particle.particle.particle import Particle


def test_oracle_001():
    assert math.isinf(width_to_lifetime(0))


def test_oracle_002():
    assert math.isinf(lifetime_to_width(0))


def test_oracle_003():
    p = Particle.from_pdgid(211)
    assert math.isclose(p.lifetime, width_to_lifetime(p.width), rel_tol=0, abs_tol=0)
    assert "Lifetime =" in p.describe()