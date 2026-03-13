import sys
import types
import numpy as np

# Create a lightweight stub of TensorFlow to allow importing pyhf in this test environment.
tf_stub = types.ModuleType("tensorflow")
# Minimal dtypes
tf_stub.float32 = "float32"
tf_stub.float64 = "float64"
# Minimal numeric ops used at import/runtime in opt_tflow
def _hessians(x, y):
    return [None]
def _gradients(x, y):
    return [None]
def _transpose(x):
    return x
def _matmul(a, b):
    return None
def _stack(x):
    return x
class linalg:
    @staticmethod
    def inv(x):
        return None
# Session stub will return an object that behaves like a zero-array when used in arithmetic / numpy
class _ZeroSub:
    def __init__(self, length):
        self._arr = np.zeros(length, dtype=float)
    def __rsub__(self, other):
        return np.array(other) - self._arr
    def __array__(self, dtype=None):
        return np.asarray(self._arr, dtype=dtype)
    def tolist(self):
        return self._arr.tolist()
class SessionStub:
    def run(self, fetches, feed_dict=None):
        # determine length from feed_dict values if possible
        if feed_dict:
            # take first entry
            v = next(iter(feed_dict.values()))
            try:
                length = len(v)
            except Exception:
                # fallback to scalar
                length = 1
        else:
            length = 1
        return _ZeroSub(length)
# attach stubs
tf_stub.hessians = _hessians
tf_stub.gradients = _gradients
tf_stub.linalg = linalg
tf_stub.transpose = _transpose
tf_stub.matmul = _matmul
tf_stub.stack = _stack
tf_stub.Session = SessionStub
# put into sys.modules so "import tensorflow as tf" yields this stub
sys.modules['tensorflow'] = tf_stub

import pyhf

def test_oracle_001():
    # The patch exposes tflow_optimizer via pyhf.__init__; before the patch this attribute didn't exist.
    assert hasattr(pyhf, "tflow_optimizer"), "pyhf.tflow_optimizer should be available after the patch"

def test_oracle_002():
    # Test that the TensorFlow optimizer's unconstrained_bestfit runs with a dummy tensorlib/session and
    # returns the initial parameters when the TF session produces zero updates.
    class DummyTB:
        def astensor(self, x):
            return x
        def concatenate(self, list_of_arrays):
            # flatten lists like [[p1], [p2], ...] -> [p1, p2, ...]
            out = []
            for item in list_of_arrays:
                if isinstance(item, (list, tuple, np.ndarray)):
                    out.extend(list(item))
                else:
                    out.append(item)
            return out
        # session attribute expected by tflow_optimizer
        session = SessionStub()
    tb = DummyTB()

    # simple objective that ignores its inputs; the TF stubs will be invoked but do nothing
    def objective(pars, data, pdf):
        return 0.0

    pdf = types = None  # not used by our dummy objective
    init_pars = [1.0, 2.0]
    par_bounds = None

    opt = pyhf.tflow_optimizer(tb)
    result = opt.unconstrained_bestfit(objective, data=[0.0], pdf=pdf, init_pars=init_pars, par_bounds=par_bounds)
    # Since our SessionStub returns zero updates, result should equal the initial parameters
    assert np.allclose(result, init_pars)

def test_oracle_003():
    # Test constrained_bestfit similarly: ensure constrained mu is inserted and nuisances preserved when updates are zero.
    class DummyTB:
        def astensor(self, x):
            return x
        def concatenate(self, list_of_arrays):
            out = []
            for item in list_of_arrays:
                if isinstance(item, (list, tuple, np.ndarray)):
                    out.extend(list(item))
                else:
                    out.append(item)
            return out
        session = SessionStub()
    tb = DummyTB()

    def objective(pars, data, pdf):
        return 0.0

    # minimal pdf with poi_index attribute used by constrained_bestfit
    class DummyPDF:
        class config:
            poi_index = 0
    pdf = DummyPDF()
    init_pars = [1.0, 2.0, 3.0]
    par_bounds = None
    constrained_mu = 0.5

    opt = pyhf.tflow_optimizer(tb)
    result = opt.constrained_bestfit(objective, constrained_mu, data=[0.0], pdf=pdf, init_pars=init_pars, par_bounds=par_bounds)
    # The constrained result should have constrained_mu at poi_index and other nuisances preserved (since updates are zero)
    expected = init_pars.copy()
    expected[pdf.config.poi_index] = constrained_mu
    assert np.allclose(result, expected)