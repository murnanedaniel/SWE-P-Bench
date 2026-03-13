import inspect

from decaylanguage.particle.particle import Particle, get_from_pdg


def test_oracle_001():
    Particle._pdg_table = None
    p = Particle.from_pdgid(211)
    assert p.latex == r"\pi^{+}"


def test_oracle_002():
    sig = inspect.signature(Particle.load_pdg_table)
    assert sig.parameters["files"].default is None
    assert sig.parameters["latexes"].default is None


def test_oracle_003():
    sig = inspect.signature(get_from_pdg)
    assert sig.parameters["latexes"].default is None