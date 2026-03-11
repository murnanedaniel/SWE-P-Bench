import awkward as ak

def test_oracle_001():
    # Integer NumpyArray: buffer is produced as big-endian ndarray; from_buffers must respect byteorder
    array = ak.Array([1, 2, 3])
    form, length, container = ak.to_buffers(array, byteorder=">")
    reconstructed = ak.from_buffers(form, length, container, byteorder=">")
    assert ak.to_list(reconstructed) == [1, 2, 3]

def test_oracle_002():
    # Floating-point NumpyArray with negative value: ensure big-endian floats are interpreted correctly
    array = ak.Array([1.5, 2.5, -3.25])
    form, length, container = ak.to_buffers(array, byteorder=">")
    reconstructed = ak.from_buffers(form, length, container, byteorder=">")
    assert ak.to_list(reconstructed) == [1.5, 2.5, -3.25]

def test_oracle_003():
    # Nested lists containing integers: ensures byteorder is applied to inner NumpyArray buffers
    array = ak.Array([[1, 2], [], [3]])
    form, length, container = ak.to_buffers(array, byteorder=">")
    reconstructed = ak.from_buffers(form, length, container, byteorder=">")
    assert ak.to_list(reconstructed) == [[1, 2], [], [3]]