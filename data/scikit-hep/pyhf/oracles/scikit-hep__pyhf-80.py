import importlib
import sys
import types
import numpy as np

def _inject_fake_mxnet(nd_impl):
    mxnet_mod = types.ModuleType("mxnet")
    mxnet_mod.nd = nd_impl
    sys.modules["mxnet"] = mxnet_mod

def _remove_module(name):
    if name in sys.modules:
        del sys.modules[name]

def _reload_pyhf():
    # Ensure a fresh import of pyhf from the working tree
    _remove_module("pyhf.tensor.mxnet_backend")
    _remove_module("pyhf.tensor")
    _remove_module("pyhf")
    return importlib.import_module("pyhf")

def test_oracle_001():
    # Test that pyhf exposes mxnet_backend at top-level when mxnet is importable
    class DummyND: pass
    _inject_fake_mxnet(DummyND())
    try:
        pyhf = _reload_pyhf()
        assert hasattr(pyhf, "mxnet_backend") and callable(pyhf.mxnet_backend)
    finally:
        # cleanup
        _remove_module("mxnet")
        _remove_module("pyhf.tensor.mxnet_backend")
        _remove_module("pyhf.tensor")
        _remove_module("pyhf")

def test_oracle_002():
    # Test that mxnet_backend.tolist uses nd.array(...).asnumpy().tolist()
    class FakeArray:
        def __init__(self, arr):
            self._arr = np.array(arr)
        def asnumpy(self):
            return self._arr

    class FakeND:
        def array(self, x):
            return FakeArray(x)
    _inject_fake_mxnet(FakeND())
    try:
        pyhf = _reload_pyhf()
        # instantiate backend and use tolist
        backend = pyhf.mxnet_backend()
        out = backend.tolist([1, 2, 3])
        assert out == [1, 2, 3]
    finally:
        _remove_module("mxnet")
        _remove_module("pyhf.tensor.mxnet_backend")
        _remove_module("pyhf.tensor")
        _remove_module("pyhf")

def test_oracle_003():
    # Test that the mxnet backend module is importable from the package
    class DummyND: pass
    _inject_fake_mxnet(DummyND())
    try:
        _remove_module("pyhf.tensor.mxnet_backend")
        pyhf = _reload_pyhf()
        mod = importlib.import_module("pyhf.tensor.mxnet_backend")
        assert hasattr(mod, "mxnet_backend")
    finally:
        _remove_module("mxnet")
        _remove_module("pyhf.tensor.mxnet_backend")
        _remove_module("pyhf.tensor")
        _remove_module("pyhf")