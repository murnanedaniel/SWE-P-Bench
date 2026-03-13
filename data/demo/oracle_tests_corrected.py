# Manually corrected oracle tests (original had wrong ak.to_buffers return order)
# GPT-5-mini generated: form, buffers, length = ak.to_buffers(...)
# Actual API is:         form, length, container = ak.to_buffers(...)

import awkward as ak
import numpy as np


def _force_ndarray_buffers(container):
    # Convert bytes buffers -> numpy arrays to force ndarray code path
    result = {}
    for k, v in container.items():
        if isinstance(v, (bytes, bytearray)):
            result[k] = np.frombuffer(v, dtype=np.uint8)
        else:
            result[k] = v
    return result


def test_oracle_001():
    array = ak.Array([1, 2, 3])
    form, length, container = ak.to_buffers(array, byteorder=">")
    container = _force_ndarray_buffers(container)
    reconstructed = ak.from_buffers(form, length, container, byteorder=">")
    assert ak.to_list(reconstructed) == [1, 2, 3]


def test_oracle_002():
    array = ak.Array([1.5, 2.25, -3.125])
    form, length, container = ak.to_buffers(array, byteorder=">")
    container = _force_ndarray_buffers(container)
    reconstructed = ak.from_buffers(form, length, container, byteorder=">")
    assert ak.to_list(reconstructed) == [1.5, 2.25, -3.125]


def test_oracle_003():
    array = ak.Array([[1, 2], [3]])
    form, length, container = ak.to_buffers(array, byteorder=">")
    container = _force_ndarray_buffers(container)
    reconstructed = ak.from_buffers(form, length, container, byteorder=">")
    assert ak.to_list(reconstructed) == [[1, 2], [3]]
