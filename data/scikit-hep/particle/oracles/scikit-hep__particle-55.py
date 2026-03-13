import particle
try:
    import importlib_resources as resources
except Exception:
    import importlib.resources as resources
import pkgutil

def test_oracle_001():
    # The package data file must be available as a resource and contain the header "name".
    content = resources.read_text("particle.data", "particle2018.csv")
    assert "name" in content

def test_oracle_002():
    # Opening the resource via open_text should succeed and its first line should mention "pdgid" or "name".
    with resources.open_text("particle.data", "particle2018.csv") as f:
        first = f.readline().lower()
    assert ("pdgid" in first) or ("name" in first)

def test_oracle_003():
    # pkgutil.get_data should return the CSV bytes (not None) and include the "name" field.
    data = pkgutil.get_data("particle.data", "particle2018.csv")
    assert data is not None
    assert b"name" in data.lower()