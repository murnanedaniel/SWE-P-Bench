from particle import Particle

def _mass_gt_500(p):
    try:
        return (p.mass is not None) and (p.mass > 500)
    except Exception:
        return False

def test_oracle_001():
    # Positional callable: select particles by inspecting particle.mass
    matches = Particle.from_search_list(_mass_gt_500)
    assert any(getattr(m, "pdgid", None) == 2212 for m in matches)

def test_oracle_002():
    # Keyword callable: mass is called with the particle's mass value
    matches = Particle.from_search_list(mass=lambda m: (m is not None) and (m > 500))
    assert any(getattr(m, "pdgid", None) == 2212 for m in matches)

def test_oracle_003():
    # Positional callable combined with particle=True should return only particles (not antiparticles)
    matches = Particle.from_search_list(_mass_gt_500, particle=True)
    assert matches, "Expected at least one match"
    # All returned entries should be particles (positive PDGID)
    assert all(int(m) > 0 for m in matches)
    assert any(getattr(m, "pdgid", None) == 2212 for m in matches)