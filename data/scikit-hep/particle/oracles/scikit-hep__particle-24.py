import re
import particle.data as data


def test_oracle_001():
    "Ensure pdgid 21 (gluon) appears in the pdgid_to_latex mapping."
    with data.open_text(data, 'pdgid_to_latex.csv') as fh:
        txt = fh.read()
    assert re.search(r'(?m)^21,', txt), "pdgid 21 missing from pdgid_to_latex.csv"


def test_oracle_002():
    "Ensure pdgid 5332 (Omega_b) appears in the pdgid_to_latex mapping."
    with data.open_text(data, 'pdgid_to_latex.csv') as fh:
        txt = fh.read()
    # require the exact PDG id at the start of a line
    assert re.search(r'(?m)^5332,', txt), "pdgid 5332 missing from pdgid_to_latex.csv"


def test_oracle_003():
    "Ensure pdgid 1000223 (omega(1420)) appears in the 2018 particle table."
    with data.open_text(data, 'particle2018.csv') as fh:
        txt = fh.read()
    assert re.search(r'(?m)^1000223,', txt), "pdgid 1000223 missing from particle2018.csv"