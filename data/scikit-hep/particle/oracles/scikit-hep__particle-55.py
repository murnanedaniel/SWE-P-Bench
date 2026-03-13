import pytest
from particle import Particle


def test_oracle_001_particle_table_can_be_loaded_for_pdgid_query():
    p = Particle.from_pdgid(11)
    assert p.pdgid == 11


def test_oracle_002_particle_table_can_be_loaded_for_antiparticle_query():
    p = Particle.from_pdgid(-11)
    assert p.pdgid == -11


def test_oracle_003_particle_table_supports_multiple_independent_queries():
    first = Particle.from_pdgid(13)
    second = Particle.from_pdgid(211)
    assert first.pdgid == 13
    assert second.pdgid == 211