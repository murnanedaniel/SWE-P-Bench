import pytest

from particle import PDGID


def test_oracle_001_particle_exports_pythiaid():
    import particle

    assert hasattr(particle, "PythiaID")
    pyid = particle.PythiaID(211)
    assert pyid.to_pdgid() == PDGID(211)


def test_oracle_002_pythiaid_from_pdgid_nontrivial_translation():
    from particle import PythiaID

    assert PythiaID.from_pdgid(PDGID(9010221)) == PythiaID(10221)


def test_oracle_003_bimap_bidirectional_nontrivial_translation():
    from particle import Pythia2PDGIDBiMap, PythiaID

    assert Pythia2PDGIDBiMap[PDGID(9010221)] == PythiaID(10221)
    assert Pythia2PDGIDBiMap[PythiaID(10221)] == PDGID(9010221)