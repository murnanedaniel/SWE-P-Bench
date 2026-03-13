import importlib
import decaylanguage


def _get_evtgen_module():
    return importlib.import_module("decaylanguage.evtgen")


def test_oracle_001():
    # Fails if the submodule decaylanguage.evtgen does not exist (buggy code).
    mod = _get_evtgen_module()
    # Passes when the submodule is present after the fix.
    assert mod is not None


def test_oracle_002():
    # Ensure the imported module has the expected module name.
    mod = _get_evtgen_module()
    assert getattr(mod, "__name__", "") == "decaylanguage.evtgen"


def test_oracle_003():
    # Sanity check that the module is a proper Python module object with a dict.
    mod = _get_evtgen_module()
    assert isinstance(getattr(mod, "__dict__", None), dict)