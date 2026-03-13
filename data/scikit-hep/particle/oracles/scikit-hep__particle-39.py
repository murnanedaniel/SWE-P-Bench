import math

from particle.kinematics import lifetime_to_width, width_to_lifetime
from particle import Particle


def test_oracle_001():
    assert math.isinf(width_to_lifetime(0))


def test_oracle_002():
    assert math.isinf(lifetime_to_width(0))


def test_oracle_003():
    p = Particle.from_pdgid(11)
    assert math.isinf(p.lifetime)