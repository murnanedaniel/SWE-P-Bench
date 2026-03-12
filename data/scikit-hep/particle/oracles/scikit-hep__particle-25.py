import particle


def test_oracle_001():
    # PythiaID class must be exported from package
    assert hasattr(particle, "PythiaID")
    PythiaID = particle.PythiaID
    PDGID = particle.PDGID

    # Basic construction and conversion to PDGID
    p = PythiaID(211)
    pdg = p.to_pdgid()
    assert isinstance(pdg, PDGID)
    assert int(pdg) == 211


def test_oracle_002():
    PythiaID = particle.PythiaID
    PDGID = particle.PDGID

    # Construct a PythiaID from a PDGID (mapping present in data file)
    py = PythiaID.from_pdgid(PDGID(9010221))
    assert isinstance(py, PythiaID)
    assert int(py) == 10221


def test_oracle_003():
    # BiMap must be available and perform round-trip lookups
    assert hasattr(particle, "Pythia2PDGIDBiMap")
    b = particle.Pythia2PDGIDBiMap

    pdg = particle.PDGID(9010221)
    py = b[pdg]
    assert int(py) == 10221

    pdg2 = b[particle.PythiaID(10221)]
    assert int(pdg2) == 9010221