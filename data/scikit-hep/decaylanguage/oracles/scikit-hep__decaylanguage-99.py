import builtins
import importlib
import sys

import pytest


def _clear_decaylanguage_modules():
    for name in list(sys.modules):
        if name == "decaylanguage" or name.startswith("decaylanguage."):
            sys.modules.pop(name, None)


def _block_pydot_import(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "pydot" or name.startswith("pydot."):
            raise ImportError("simulated missing pydot")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_oracle_001_top_level_import_decfileparser_without_pydot(monkeypatch):
    _clear_decaylanguage_modules()
    _block_pydot_import(monkeypatch)

    decaylanguage = importlib.import_module("decaylanguage")

    assert hasattr(decaylanguage, "DecFileParser")


def test_oracle_002_decay_subpackage_import_without_pydot(monkeypatch):
    _clear_decaylanguage_modules()
    _block_pydot_import(monkeypatch)

    decay_mod = importlib.import_module("decaylanguage.decay")

    assert hasattr(decay_mod, "DecayChain")


def test_oracle_003_decay_subpackage_omits_viewer_when_pydot_missing(monkeypatch):
    _clear_decaylanguage_modules()
    _block_pydot_import(monkeypatch)

    decay_mod = importlib.import_module("decaylanguage.decay")

    assert not hasattr(decay_mod, "DecayChainViewer")