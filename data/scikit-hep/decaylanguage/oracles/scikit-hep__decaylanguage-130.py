import inspect
from collections import OrderedDict

import decaylanguage.modeling.ampgentransform as ampgentransform


class _FakeFirst:
    def __init__(self, children):
        self.children = children


class _FakeLine:
    def __init__(self, data):
        self.data = data


def _find_transformer_class(module):
    for _, obj in vars(module).items():
        if inspect.isclass(obj) and hasattr(obj, "decay"):
            # ensure it's instantiable without args
            try:
                inst = obj()
            except Exception:
                continue
            # found a class with a usable decay method
            return obj
    raise RuntimeError("No suitable transformer class with a decay method found")


def _make_simple_lines():
    # First element must have .children attribute and contain one particle-like object
    first = _FakeFirst(children=["ParticleX"])
    # No further lines needed for minimal behavior
    return [first]


def test_oracle_001():
    """decay should produce an OrderedDict (not a plain dict)."""
    cls = _find_transformer_class(ampgentransform)
    inst = cls()
    lines = _make_simple_lines()
    result = inst.decay(lines)
    assert isinstance(result, OrderedDict)


def test_oracle_002():
    """decay must return an instance whose exact type is collections.OrderedDict."""
    cls = _find_transformer_class(ampgentransform)
    inst = cls()
    lines = _make_simple_lines()
    result = inst.decay(lines)
    assert type(result) is OrderedDict


def test_oracle_003():
    """Returned mapping should have keys in the expected order and be OrderedDict."""
    cls = _find_transformer_class(ampgentransform)
    inst = cls()
    lines = _make_simple_lines()
    result = inst.decay(lines)
    assert list(result.keys()) == ["name", "daughters"]
    assert isinstance(result, OrderedDict)