from particle import Particle


def test_oracle_001():
    # Electron (PDG ID 11) is a fermion; spin_type should be NonDefined for fermions.
    p = Particle.from_pdgid(11)
    assert p.spin_type.name == "NonDefined"


def test_oracle_002():
    # Muon (PDG ID 13) is a fermion; spin_type should be NonDefined for fermions.
    p = Particle.from_pdgid(13)
    assert p.spin_type.name == "NonDefined"


def test_oracle_003():
    # Proton (PDG ID 2212) is a baryon (fermion); spin_type should be NonDefined for fermions.
    p = Particle.from_pdgid(2212)
    assert p.spin_type.name == "NonDefined"