import pytest
from particle import Particle


def test_oracle_001():
    results = Particle.from_search_list(mass=lambda m: m > 900)
    assert any(p.name == "p" for p in results)
    assert all(p.mass > 900 for p in results)


def test_oracle_002():
    results = Particle.from_search_list(lambda p: p.name == "p", particle=True)
    assert len(results) == 1
    assert results[0].name == "p"
    assert int(results[0]) > 0


def test_oracle_003():
    particle = Particle.from_search(lambda p: p.name == "p", particle=True)
    assert particle.name == "p"
    assert int(particle) > 0