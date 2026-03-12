import pytest
from particle import Particle

def test_oracle_001():
    # Should accept a callable for a numeric property (mass) and return matches.
    results = Particle.from_search_list(mass=lambda m: True)
    assert len(results) > 0

def test_oracle_002():
    # Should accept a positional callable filter that inspects the particle object.
    results = Particle.from_search_list(lambda p: 'p' in p.fullname)
    assert len(results) > 0

def test_oracle_003():
    # from_search should accept a positional callable and return exactly one match.
    p = Particle.from_search(lambda p: p.fullname == 'pi0')
    assert p.fullname == 'pi0'