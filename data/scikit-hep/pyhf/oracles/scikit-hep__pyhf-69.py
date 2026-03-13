import math

import pyhf


def _make_shapesys_spec():
    return {
        "channels": [
            {
                "name": "singlechannel",
                "samples": [
                    {
                        "name": "signal",
                        "data": [5.0, 10.0],
                        "modifiers": [{"name": "mu", "type": "normfactor", "data": None}],
                    },
                    {
                        "name": "background",
                        "data": [50.0, 60.0],
                        "modifiers": [
                            {"name": "bkg_stat", "type": "shapesys", "data": [5.0, 6.0]}
                        ],
                    },
                ],
            }
        ],
        "observations": [{"name": "singlechannel", "data": [52.0, 63.0]}],
        "measurements": [
            {
                "name": "measurement",
                "config": {"poi": "mu", "parameters": []},
            }
        ],
        "version": "1.0.0",
    }


def _set_pytorch_backend():
    pyhf.set_backend("pytorch")
    return pyhf.tensorlib


def test_oracle_001():
    tb = _set_pytorch_backend()
    model = pyhf.Model(_make_shapesys_spec())
    data = tb.astensor([52.0, 63.0] + model.config.auxdata)
    pars = tb.astensor(model.config.suggested_init())
    value = model.logpdf(pars, data)
    assert math.isfinite(float(tb.tolist(value)))


def test_oracle_002():
    tb = _set_pytorch_backend()
    model = pyhf.Model(_make_shapesys_spec())
    pars = tb.astensor(model.config.suggested_init())
    expected = tb.tolist(model.expected_data(pars))
    assert len(expected) == 4
    assert expected[0] == 55.0
    assert expected[1] == 70.0
    assert expected[2] == 100.0
    assert expected[3] == 100.0


def test_oracle_003():
    tb = _set_pytorch_backend()
    model = pyhf.Model(_make_shapesys_spec())
    pars = tb.astensor(model.config.suggested_init())
    rates = tb.tolist(model.expected_actualdata(pars))
    assert rates == [55.0, 70.0]