import inspect

from decaylanguage.decay.amplitudechain import AmplitudeChain
from decaylanguage.decay.goofit import GooFitChain
from decaylanguage.decay import ampgen2goofit


def test_oracle_001():
    assert hasattr(AmplitudeChain, "read_ampgen")
    assert not hasattr(AmplitudeChain, "read_AmpGen")


def test_oracle_002():
    assert hasattr(GooFitChain, "read_ampgen")
    assert not hasattr(GooFitChain, "read_AmpGen")


def test_oracle_003():
    source = inspect.getsource(ampgen2goofit.ampgen2goofit)
    assert "read_ampgen" in source
    assert "read_AmpGen" not in source