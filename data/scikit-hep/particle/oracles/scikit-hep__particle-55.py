import importlib
import os

import pytest
from particle import Particle


def test_oracle_001_particle_data_csv_is_packaged():
    data_module = importlib.import_module("particle.data")
    package_dir = os.path.dirname(data_module.__file__)
    assert os.path.isfile(os.path.join(package_dir, "particle2018.csv"))


def test_oracle_002_particle_query_uses_packaged_csv():
    p = Particle.from_pdgid(11)
    assert p.pdgid == 11


def test_oracle_003_antiparticle_query_uses_packaged_csv():
    p = Particle.from_pdgid(-11)
    assert p.pdgid == -11