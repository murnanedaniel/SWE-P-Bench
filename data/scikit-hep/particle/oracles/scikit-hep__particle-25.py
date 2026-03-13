import importlib

import pytest
import particle


def test_oracle_001():
    assert hasattr(particle, "PythiaID")
    pythia_cls = particle.PythiaID
    assert repr(pythia_cls(211)) == "<PythiaID: 211>"


def test_oracle_002():
    particle_mod = importlib.import_module("particle")
    assert hasattr(particle_mod, "Pythia2PDGIDBiMap")
    pdgid = particle_mod.PDGID(9010221)
    pythiaid = particle_mod.Pythia2PDGIDBiMap[pdgid]
    assert repr(pythiaid) == "<PythiaID: 10221>"


def test_oracle_003():
    pythia_mod = importlib.import_module("particle.pythia")
    pythiaid = pythia_mod.PythiaID(10221)
    assert pythiaid.to_pdgid() == particle.PDGID(9010221)