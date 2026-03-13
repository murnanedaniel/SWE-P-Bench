import pyhf


def test_oracle_001():
    doc = pyhf.set_backend.__doc__
    assert "import pyhf.tensor as tensor" in doc


def test_oracle_002():
    doc = pyhf.set_backend.__doc__
    assert "pyhf.set_backend(tensor.tensorflow_backend(session=tf.Session()))" in doc


def test_oracle_003():
    doc = pyhf.set_backend.__doc__
    assert "pyhf.set_backend(tensorflow_backend(session=tf.Session()))" not in doc