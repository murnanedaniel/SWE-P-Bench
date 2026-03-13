import math
import numpy as np
import pyhf


def test_oracle_001():
    n = 2.5
    lam = 3.7
    expected = math.exp(n * math.log(lam) - lam - math.lgamma(n + 1.0))
    result = pyhf._poisson_impl(n, lam)
    assert np.isclose(result, expected, rtol=1e-12, atol=0.0)


def test_oracle_002():
    n = 4.0
    lam = 2.3
    expected = math.exp(n * math.log(lam) - lam - math.lgamma(n + 1.0))
    result = pyhf._poisson_impl(n, lam)
    assert np.isclose(result, expected, rtol=1e-12, atol=0.0)


def test_oracle_003():
    n = np.array([0.5, 1.5, 2.5])
    lam = 1.7
    expected = np.exp(n * np.log(lam) - lam - np.vectorize(math.lgamma)(n + 1.0))
    result = pyhf._poisson_impl(n, lam)
    assert np.allclose(result, expected, rtol=1e-12, atol=0.0)