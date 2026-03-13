import importlib

def _find_method_in_module(module, method_name):
    for name in dir(module):
        obj = getattr(module, name)
        # Check classes and objects that may define method_name
        if hasattr(obj, method_name):
            return getattr(obj, method_name)
    return None

def test_oracle_001():
    # Verify DecayChainViewer (viewer module) exposes a _repr_mimebundle_ method
    # that delegates to self._graph._repr_mimebundle_ when available.
    viewer_mod = importlib.import_module("decaylanguage.decay.viewer")
    method = _find_method_in_module(viewer_mod, "_repr_mimebundle_")
    assert method is not None, "Expected _repr_mimebundle_ in viewer module (patched code)"

    # Create fake self with a graph exposing _repr_mimebundle_
    class FakeGraph:
        def _repr_mimebundle_(self, include=None, exclude=None, **kwargs):
            return {"image/svg+xml": "<svg>from_mimebundle</svg>", "other": 123}

    class FakeSelf:
        _graph = FakeGraph()

    res = method(FakeSelf(), include=None, exclude=None)
    assert isinstance(res, dict)
    assert res.get("image/svg+xml") == "<svg>from_mimebundle</svg>"

def test_oracle_002():
    # Verify viewer._repr_mimebundle_ falls back to graph._repr_svg_ when
    # the graph lacks _repr_mimebundle_ (compat for graphviz <0.19).
    viewer_mod = importlib.import_module("decaylanguage.decay.viewer")
    method = _find_method_in_module(viewer_mod, "_repr_mimebundle_")
    assert method is not None, "Expected _repr_mimebundle_ in viewer module (patched code)"

    class FakeGraph:
        def _repr_svg_(self):
            return "<svg>from_svg</svg>"

    class FakeSelf:
        _graph = FakeGraph()

    res = method(FakeSelf(), include=None, exclude=None)
    assert isinstance(res, dict)
    assert res == {"image/svg+xml": "<svg>from_svg</svg>"}

def test_oracle_003():
    # Verify modeling.decay defines a _repr_mimebundle_ that delegates to
    # _make_graphviz()._repr_mimebundle_ (or falls back to _repr_svg_).
    decay_mod = importlib.import_module("decaylanguage.modeling.decay")
    method = _find_method_in_module(decay_mod, "_repr_mimebundle_")
    assert method is not None, "Expected _repr_mimebundle_ in modeling.decay (patched code)"

    # Primary path: _make_graphviz returns graph with _repr_mimebundle_
    class FakeGraph:
        def _repr_mimebundle_(self, include=None, exclude=None, **kwargs):
            return {"image/svg+xml": "<svg>decay_mimebundle</svg>"}

    class FakeSelf:
        def _make_graphviz(self):
            return FakeGraph()

    res = method(FakeSelf(), include=None, exclude=None)
    assert isinstance(res, dict)
    assert res.get("image/svg+xml") == "<svg>decay_mimebundle</svg>"