import pytest
from particle import Particle


def test_oracle_001_from_search_list_accepts_callable_keyword_for_real_valued_property():
    results = Particle.from_search_list(mass=lambda m: m > 1000)
    assert results
    assert all(p.mass > 1000 for p in results)


def test_oracle_002_from_search_list_accepts_particle_predicate_callable():
    results = Particle.from_search_list(lambda p: p.mass > 1000)
    assert results
    assert all(p.mass > 1000 for p in results)


def test_oracle_003_from_search_forwards_positional_predicate():
    particle = Particle.from_search(lambda p: p.name == "p" and p.three_charge == 3)
    assert particle.name == "p"
    assert particle.three_charge == 3