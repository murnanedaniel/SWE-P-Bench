import numpy as np
import pyhf


def test_oracle_001():
    func = pyhf._hfinterp_code0(1.0, 2.0, 4.0)
    alpha = np.array([-1.0, 0.0, 0.5, 2.0])
    result = func(alpha)
    expected = np.array([-1.0, 0.0, 1.0, 4.0])
    np.testing.assert_allclose(result, expected)


def test_oracle_002():
    func = pyhf._hfinterp_code1(1.0, 2.0, 8.0)
    alpha = np.array([-2.0, -1.0, 0.0, 1.0, 2.0])
    result = func(alpha)
    expected = np.array([0.25, 0.5, 1.0, 4.0, 16.0])
    np.testing.assert_allclose(result, expected)


def test_oracle_003():
    func = pyhf._hfinterp_code1(
        np.array([1.0, 4.0]),
        np.array([2.0, 2.0]),
        np.array([8.0, 8.0]),
    )
    alpha = np.array([-1.0, 1.0])
    result = func(alpha)
    expected = np.array([0.5, 4.0])
    np.testing.assert_allclose(result, expected)