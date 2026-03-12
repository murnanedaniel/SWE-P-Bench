import pytest
from particle.particle.kinematics import width_to_lifetime, lifetime_to_width
from particle.particle.particle import Particle

def test_oracle_001():
    # width == 0 should map to infinite lifetime after the fix
    assert width_to_lifetime(0.0) == float('inf')

def test_oracle_002():
    # lifetime == 0 should map to infinite width after the fix
    assert lifetime_to_width(0.0) == float('inf')

def test_oracle_003():
    # The Particle class should provide a lifetime property that returns inf for width == 0.
    # Construct an instance without calling __init__ to avoid signature differences between versions.
    p = object.__new__(Particle)
    # Set the minimal attribute used by the lifetime property
    p.width = 0.0
    # Accessing p.lifetime must exist and return infinity in the fixed code.
    assert getattr(p, "lifetime") == float('inf')