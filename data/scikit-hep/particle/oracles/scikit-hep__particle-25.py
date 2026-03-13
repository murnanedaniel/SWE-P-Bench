import particle
from particle import PDGID

def test_oracle_001():
    # The package must expose the PythiaID class at the top-level.
    assert hasattr(particle, "PythiaID"), "particle.PythiaID is not available"

def test_oracle_002():
    # PythiaID should be constructible from a PDG integer via from_pdgid
    PythiaID = particle.PythiaID
    py = PythiaID.from_pdgid(211)
    assert isinstance(py, PythiaID)
    assert int(py) == 211

def test_oracle_003():
    # The bi-directional map must translate between PDGID and PythiaID for a known mapping.
    bimap = particle.Pythia2PDGIDBiMap
    pdg_obj = PDGID(9010221)
    py = bimap[pdg_obj]
    assert isinstance(py, particle.PythiaID)
    assert int(py) == 10221
    # Reverse lookup
    pdg_back = bimap[particle.PythiaID(10221)]
    assert isinstance(pdg_back, PDGID)
    assert int(pdg_back) == 9010221
    # And PythiaID.to_pdgid should round-trip
    assert int(particle.PythiaID(10221).to_pdgid()) == 9010221