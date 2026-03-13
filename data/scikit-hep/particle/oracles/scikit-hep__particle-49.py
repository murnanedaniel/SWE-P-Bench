from particle.particle.particle import Particle
from particle.particle.enums import Inv


def test_oracle_001():
    # photon should not show "0" charge in fullname (was "gamma0" before the fix)
    p = object.__new__(Particle)
    p.name = 'gamma'
    p.pdgid = 22
    p.three_charge = 0
    p.anti = Inv.Same
    assert Particle.__str__(p) == 'gamma'


def test_oracle_002():
    # proton should not show a '+' in fullname (was "p+" before the fix)
    p = object.__new__(Particle)
    p.name = 'p'
    p.pdgid = 2212
    p.three_charge = 3
    p.anti = Inv.Full
    assert Particle.__str__(p) == 'p'


def test_oracle_003():
    # anti-up quark should show tilde but not the fractional charge (was "u~+2/3" before the fix)
    p = object.__new__(Particle)
    p.name = 'u'
    p.pdgid = -2
    p.three_charge = 2
    p.anti = Inv.Full
    assert Particle.__str__(p) == 'u~'