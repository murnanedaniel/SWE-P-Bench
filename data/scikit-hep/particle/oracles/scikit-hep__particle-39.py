import math
import pytest

from particle.particle.kinematics import width_to_lifetime, lifetime_to_width
from particle.particle.particle import Particle

def test_oracle_001():
    # width = 0 should return infinite lifetime (was raising ValueError before the fix)
    tau = width_to_lifetime(0)
    assert math.isinf(tau) and tau > 0

def test_oracle_002():
    # lifetime = 0 should return infinite width (was raising ValueError before the fix)
    gamma = lifetime_to_width(0)
    assert math.isinf(gamma) and gamma > 0

def test_oracle_003():
    # Particle instances should expose lifetime and ctau properties.
    # Use a particle with a non-zero width (e.g. rho0, PDGID 113) so lifetime is finite.
    p = Particle.from_pdgid(113)
    # lifetime should match width_to_lifetime(width)
    assert math.isfinite(p.lifetime)
    assert p.lifetime == pytest.approx(width_to_lifetime(p.width), rel=1e-12)
    # ctau should equal c_light (299.792458 mm/ns) times lifetime (result in mm)
    expected_ctau = 299.792458 * p.lifetime
    assert p.ctau == pytest.approx(expected_ctau, rel=1e-12)